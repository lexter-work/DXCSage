"""Reading the state of a SAP Software Update Manager (SUM) session from its files. Pure functions, no SSH.

States: RUNNING, WAITING_INPUT, ERROR, POSSIBLE_HANG, PROCESS_DEAD, COMPLETED, OFFLINE (no SUM on the host), UNKNOWN.
Ported from the old monitoring tool. The file formats were confirmed on one system only (SUM 2.0, S/4HANA conversion).
"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime

XML_STATE = {
    "slp.task.state.DIALOG": "WAITING_INPUT", "slp.task.state.WAITING": "WAITING_INPUT", "slp.task.state.RUNNING": "RUNNING",
    "slp.task.state.OK": "COMPLETED", "slp.task.state.FINISHED": "COMPLETED",
    "slp.task.state.ERROR": "ERROR", "slp.task.state.ABORTED": "ERROR", "slp.task.state.CANCELLED": "ERROR",
}

# (id prefixes, phase), first match wins
PHASES: list[tuple[tuple[str, ...], str]] = [
    (("MOD_", "PREP_EXTRACT", "PREP_PRE_CHECK", "PREP_INPUT", "PREP_INIT", "PREP_CHKIMPORT", "PREP_IMPORT", "PREP_PARSETUP"), "Extraction"),
    (("PREP_CONFIGURATION", "PREP_CONFIG", "PREP_EXTENSION", "PREP_SHDTABLES"), "Configuration"),
    (("PREP_GENCHECKS", "PREP_SPACECALC", "BW4HCONV_CHECK"), "Checks"),
    (("EU_", "MAIN_DTTRANS"), "Preprocessing"),
    (("MAIN_SHDRUN", "MAIN_NEWBAS", "MAIN_"), "Execution"),
    (("POST_", "ACT_"), "Postprocessing"),
]
# Rough minutes a phase may stay silent before it is called a possible hang (not measured on real runs).
EXPECTED_MIN = {"Extraction": 30, "Configuration": 15, "Checks": 20, "Preprocessing": 90, "Execution": 180, "Postprocessing": 60}
BASE_HANG_MIN = 30


def phase_of(task_id: str) -> str:
    up = task_id.upper()
    for prefixes, phase in PHASES:
        if up.startswith(prefixes):
            return phase
    return "Unknown"


def _ts(value: str) -> datetime | None:
    value = (value or "").strip()
    for fmt in ("%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _ident(task: ET.Element) -> str:
    return task.findtext("technicalName", "") or task.findtext("id", "")


def parse_observer_xml(xml: str) -> dict | None:
    """The state from SUMOBSERVER.XML, or None when it is unreadable or no task has a known state."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    tasks = root.findall(".//Task")
    if not tasks:
        return None

    def when(t):
        return _ts(t.findtext("statusChangedAt", "")) or _ts(t.findtext("dialogTime", "")) or _ts(t.findtext("startedAt", "")) or datetime.min

    # The newest dialog or waiting task wins (a resolved earlier dialog keeps its stale state), then a running one, then the last task.
    best, best_ts = None, datetime.min
    for t in tasks:
        st = t.findtext("status", "")
        if st in ("slp.task.state.DIALOG", "slp.task.state.WAITING"):
            if best is None or when(t) >= best_ts:
                best, best_ts = t, when(t)
        elif st == "slp.task.state.RUNNING" and best is None:
            best = t
    best = best if best is not None else tasks[-1]
    state = XML_STATE.get(best.findtext("status", ""))
    if state is None:
        return None

    root_task = next((t for t in tasks if not t.findtext("parent", "")), best)        # the GUI percentage is the root task's progress
    try:
        pct = float(root_task.findtext("progress", "0"))
    except ValueError:
        pct = None

    parents = {i: t.findtext("parent", "") for t in tasks if (i := t.findtext("id", ""))}
    by_id = {i: t for t in tasks if (i := t.findtext("id", ""))}
    own = best.findtext("id", "")
    task_id, parent = _ident(best), best.findtext("parent", "")
    detail = f"{parent}/{task_id}" if parent and parent != task_id else task_id
    cur, child, seen = own, None, set()                                  # climb to the roadmap step the GUI shows as "Current Phase"
    while cur and cur not in seen:
        seen.add(cur)
        if phase_of(cur) != "Unknown":
            if child:
                detail = f"{_ident(by_id[cur]) if cur in by_id else cur}/{child}"
            break
        child = _ident(by_id[cur]) if cur in by_id else cur
        cur = parents.get(cur, "")
    msg_el = best.find(".//progressMessages/ProgressMessage/message")
    raw = msg_el.text.strip() if msg_el is not None and msg_el.text else ""
    if m := re.search(r"Phase:\s*(\S+)", raw):
        detail = m.group(1)
    phase, cur, seen = "Unknown", own, set()
    while cur and cur not in seen and phase == "Unknown":
        seen.add(cur)
        phase = phase_of(cur)
        cur = parents.get(cur, "")
    est = root.find(".//estimate")
    changed = _ts(best.findtext("statusChangedAt", "")) or _ts(best.findtext("dialogTime", "")) or _ts(best.findtext("startedAt", ""))
    return {"state": state, "phase": phase, "phase_detail": detail, "progress_pct": pct, "task_id": task_id, "source": "xml",
            "time_remaining": (est.get("left") or None) if est is not None else None,
            "eta": est.text.strip() if est is not None and est.text and est.text.strip() else None,
            "message": raw or (f"SUM {state}: {detail}" if detail else f"SUM {state}"),
            "changed_at": changed.strftime("%Y%m%d%H%M%S") if changed else ""}


def parse_logs(sapup: str, stat: str) -> dict:
    """Fallback when the XML is missing: state from the end of SAPup.log, progress from SAPupStat.log."""
    state, detail = "UNKNOWN", ""
    for line in reversed(sapup.strip().splitlines()[-200:]):
        low = line.lower()
        for needle, st in (("process is in dialog state", "WAITING_INPUT"), ("task is in running state", "RUNNING"),
                           ("decided to exit completed upgrade", "COMPLETED"), ("decided to exit aborted upgrade", "ERROR")):
            if needle in low:
                state, detail = st, line.strip()
                break
        if detail:
            break
    pct = eta = left = None
    for line in reversed(stat.strip().splitlines()[-50:]):
        if m := re.search(r"(\d+\.?\d*)%\s+LEFT:\s*(\S+)\s+END:\s*(\S+)", line):
            pct, left, eta = float(m.group(1)), m.group(2), m.group(3)
            break
    return {"state": state, "phase": "Unknown", "phase_detail": detail, "progress_pct": pct, "eta": eta, "time_remaining": left, "task_id": "",
            "source": "log", "message": f"SUM {state}" + (f" ({pct:.1f}%)" if pct else ""), "changed_at": ""}


def hang_threshold(phase: str) -> int:
    return max(BASE_HANG_MIN, EXPECTED_MIN.get(phase, 0))


def minutes_between(earlier: str, later: str) -> float | None:
    a, b = _ts(earlier), _ts(later)
    return (b - a).total_seconds() / 60 if a and b else None


# ---- what to do next ---------------------------------------------------------------------------------------------------

ACTIONS = {
    "RUNNING": "Running normally. No action needed.",
    "WAITING_INPUT": "SUM waits for input in its browser UI. Open the SUM web UI for this system and answer the pending dialog.",
    "ERROR": "SUM hit an error. Read SAPup.log and the phase and message here for the failing step, then decide: retry, roll back, or escalate to Basis or SAP support.",
    "POSSIBLE_HANG": "No change for a long time. Confirm SAPup_real still runs on the host, then check SAPup.log for a step that waits on something outside SUM (for example a long database operation).",
    "PROCESS_DEAD": "SAPup_real no longer runs on the host: SUM has stopped, not just stalled. Find out what stopped it (out of memory, host reboot, manual kill) and restart SUM from its web UI. No log advances until it runs again.",
    "COMPLETED": "The upgrade completed. Verify system health and follow your post-upgrade checklist.",
    "OFFLINE": "No SUM session on this system (no SUM files and SAPup_real is not running). Nothing to do until an upgrade starts.",
    "UNKNOWN": "The state could not be read from SUMOBSERVER.XML or the SAPup logs. Check the SSH user and that SUM runs on this host.",
}
DIALOG_ACTIONS = {
    "archivemissing": "One or more required SAR archives are missing from the download directory. Check SCANDOWNLOAD.LOG in the SUM log directory and place the missing archives there, or point SUM to the right directory.",
    "sumask": "Enter the required system passwords (DDIC, SYSTEM and so on) in the SUM web UI.",
}


def required_action(state: str, task_id: str, message: str, phase_detail: str) -> str:
    if state != "WAITING_INPUT":
        return ACTIONS.get(state, ACTIONS["UNKNOWN"])
    if a := DIALOG_ACTIONS.get((task_id or "").strip().lower()):
        return a
    low = (message or "").lower()
    if "stack" in low or "configuration file" in low:
        return "Provide the stack configuration XML file in the SUM web UI."
    if "waiting in dialog" in low:
        return f"SUM waits for input at phase '{phase_detail}'. Open the SUM web UI and answer the pending dialog."
    return message or ACTIONS["WAITING_INPUT"]


# Known error signatures, most specific first; the first match wins. The SAP Note numbers come from the old tool and were not checked.
_P = lambda rx: re.compile(rx, re.IGNORECASE)  # noqa: E731
ERRORS: list[tuple[re.Pattern, dict]] = [
    (_P(r"ORA-0165[34]|tablespace.{0,20}full|unable to extend"), {"error_code": "TABLESPACE_FULL", "category": "SPACE", "severity": "HIGH",
        "root_cause": "The database tablespace is full. SUM cannot write data or indexes.",
        "recommended_fix": "1. Find the full tablespace (dba_free_space)\n2. Extend it (ALTER TABLESPACE ... ADD DATAFILE) or enable AUTOEXTEND\n3. Resume SUM",
        "sap_note": "SAP Note 2399996 - Space requirements for SUM", "auto_recoverable": True}),
    (_P(r"no space left on device|disk full|/usr/sap.{0,10}100%"), {"error_code": "DISK_FULL", "category": "SPACE", "severity": "HIGH",
        "root_cause": "The host filesystem SUM writes to (usually /usr/sap) is full.",
        "recommended_fix": "1. Check df -h /usr/sap\n2. Free space or extend the volume\n3. Resume SUM", "sap_note": "", "auto_recoverable": True}),
    (_P(r"DDL error|CREATE INDEX.{0,40}fail|duplicate key|ALTER TABLE.{0,40}fail"), {"error_code": "DDL_ERROR", "category": "DDL", "severity": "MEDIUM",
        "root_cause": "A DDL statement (CREATE INDEX or ALTER TABLE) failed, often from a leftover object or a constraint violation of an earlier partial run.",
        "recommended_fix": "1. Read the exact statement and error in SAPup.log\n2. Look for a leftover index or constraint from an earlier attempt\n3. Drop the conflicting object if safe, then resume SUM",
        "sap_note": "", "auto_recoverable": False}),
    (_P(r"lock timeout|deadlock|enqueue timeout"), {"error_code": "LOCK_TIMEOUT", "category": "LOCK", "severity": "MEDIUM",
        "root_cause": "A database or enqueue lock could not be taken in time, usually because another job or session holds the same object.",
        "recommended_fix": "1. Find the blocking session or job (SM12, SM66, or the database lock views)\n2. End it or wait for it\n3. Resume SUM", "sap_note": "", "auto_recoverable": True}),
    (_P(r"ORA-0311[34]|end-of-file on communication channel|connection lost"), {"error_code": "DB_CONNECTION_LOST", "category": "TIMEOUT", "severity": "HIGH",
        "root_cause": "The database connection dropped during an operation: a network problem, a database restart, or a killed session.",
        "recommended_fix": "1. Confirm the database instance is up and reachable\n2. Check the database alert log for a restart or crash at that time\n3. Resume SUM once the connection is stable",
        "sap_note": "", "auto_recoverable": True}),
    (_P(r"RABAX|ABAP runtime error|short dump"), {"error_code": "ABAP_RUNTIME_ERROR", "category": "ABAP", "severity": "HIGH",
        "root_cause": "An ABAP program that SUM depends on (for example a migration report) dumped.",
        "recommended_fix": "1. Find the short dump in ST22 for that time\n2. Read the runtime error and the failing program\n3. Fix the cause (often data specific), then resume SUM",
        "sap_note": "", "auto_recoverable": False}),
    (_P(r"heap area.{0,20}exceed|abap/heap_area"), {"error_code": "ABAP_HEAP_EXCEEDED", "category": "ABAP", "severity": "MEDIUM",
        "root_cause": "An ABAP work process exceeded its heap memory limit (abap/heap_area_dia or abap/heap_area_nondia).",
        "recommended_fix": "1. Check the heap parameters in RZ11\n2. Raise the one that applies if there is room, or reduce the package size SUM uses\n3. Resume SUM",
        "sap_note": "", "auto_recoverable": False}),
    (_P(r"RFC connection.{0,40}fail|NO_AUTHORITY|destination not found"), {"error_code": "RFC_CONNECTION_FAILED", "category": "CONFIG", "severity": "MEDIUM",
        "root_cause": "An RFC destination SUM needs failed to connect, or the calling user lacks authorization.",
        "recommended_fix": "1. Run the connection test of the destination in SM59\n2. Check the authorizations of the RFC user\n3. Resume SUM once the test is clean",
        "sap_note": "", "auto_recoverable": False}),
    (_P(r"tp return code [89]|transport.{0,20}error"), {"error_code": "TRANSPORT_ERROR", "category": "CONFIG", "severity": "MEDIUM",
        "root_cause": "A transport (tp) step failed with a return code that means an import error, not just a warning.",
        "recommended_fix": "1. Read the tp log (or STMS) for the object that failed\n2. Fix the object-level conflict (often a version mismatch)\n3. Run the step again, then resume SUM",
        "sap_note": "", "auto_recoverable": False}),
    (_P(r"ssh:.{0,20}connection refused|host unreachable"), {"error_code": "SSH_CONNECTION_REFUSED", "category": "NETWORK", "severity": "HIGH",
        "root_cause": "SUM could not reach the target host over SSH.",
        "recommended_fix": "1. Confirm the host is up and SSH listens (network, firewall, host status)\n2. Retry when it is reachable", "sap_note": "", "auto_recoverable": True}),
    (_P(r"SAPup aborted|1?EETQ\d+"), {"error_code": "SAPUP_ABORTED", "category": "ABAP", "severity": "HIGH",
        "root_cause": "SUM's own SAPup process aborted with an ETQ error code. The code names the failing check or step.",
        "recommended_fix": "1. Note the exact ETQ code in SAPup.log\n2. Search that code with your SUM version in SAP Notes\n3. Fix the cause and resume SUM", "sap_note": "", "auto_recoverable": False}),
    (_P(r"OutOfMemoryError|java heap space|heapdump"), {"error_code": "JVM_OOM", "category": "ABAP", "severity": "MEDIUM",
        "root_cause": "A Java based step that SUM starts ran out of heap memory.",
        "recommended_fix": "1. Find which Java step failed from the lines around it\n2. Raise its -Xmx heap if it can be set\n3. Resume SUM", "sap_note": "", "auto_recoverable": False}),
    (_P(r"background job.{0,30}abort|EU_CLONE.{0,20}(abort|fail)"), {"error_code": "BATCH_JOB_FAILED", "category": "ABAP", "severity": "MEDIUM",
        "root_cause": "A background job that SUM scheduled (for example an EU_CLONE migration job) aborted.",
        "recommended_fix": "1. Read the job log in SM37 for the real reason\n2. Fix the cause and release the job again if SUM does not\n3. Resume SUM", "sap_note": "", "auto_recoverable": False}),
]


def diagnose(text: str) -> dict | None:
    for rx, info in ERRORS:
        if m := rx.search(text):
            return {**info, "matched_text": m.group(0)}
    return None
