from pydantic import BaseModel

from sage.sap import sum as su
from sage.sap.requirements import FileReadable, SshLogin
from sage.sap.ssh import SshError
from sage.tasks.base import Task

DIR = "/usr/sap/{SID}/SUM/abap"
XML, SAPUP, STAT = f"{DIR}/doc/analysis/SUMOBSERVER.XML", f"{DIR}/log/SAPup.log", f"{DIR}/log/SAPupStat.log"
PROCESS = "SAPup_real"


class PollIn(BaseModel):
    pass


class PollOut(BaseModel):
    state: str
    phase: str = "Unknown"
    phase_detail: str = ""
    progress_pct: float | None = None
    eta: str | None = None
    time_remaining: str | None = None
    message: str = ""
    source: str = ""                  # xml | log | none
    task_id: str = ""
    changed_at: str = ""              # host time of the last status change, YYYYMMDDHHMMSS
    log_tail: str = ""                # the end of SAPup.log, only when the state is ERROR


class PollSum(Task):
    """Reads the files of SUM on the host over SSH: SUMOBSERVER.XML first, the SAPup logs when it is missing, then checks that
    SAPup_real runs. Read-only. Needs optional SSH access on the system."""
    name, Input, Output = "sum.poll_state", PollIn, PollOut
    requirements = (SshLogin(), FileReadable(XML, level="warn", guide="SUMOBSERVER.XML exists only while SUM has a session. Without it Sage falls back to the SAPup logs."),
                    FileReadable(SAPUP, level="warn", guide="SAPup.log exists only while SUM has a session."))

    async def run(self, ctx, data):
        ssh, sid, sysid = ctx.ssh, ctx.sid.upper(), ctx.system_id
        paths = {k: v.replace("{SID}", sid) for k, v in (("xml", XML), ("sapup", SAPUP), ("stat", STAT))}

        async def read(path, tail=0):
            try:
                return await ssh.read_file(sysid, path, tail)
            except SshError as e:
                if e.code != "READ":                      # a missing file is normal when SUM is not running; anything else is a real problem
                    raise
                return ""

        saw, status = False, None
        xml = await read(paths["xml"])
        if xml.strip():
            saw, status = True, su.parse_observer_xml(xml)
        if status is None:
            sapup, stat = await read(paths["sapup"], 200), await read(paths["stat"], 50)
            saw = saw or bool(sapup.strip() or stat.strip())
            status = su.parse_logs(sapup, stat)
        if not saw and status["state"] == "UNKNOWN":
            status = {**status, "source": "none"}

        if status["state"] in ("RUNNING", "UNKNOWN") and not await ssh.process_running(sysid, PROCESS):
            if status["state"] == "UNKNOWN" and not saw:
                status = {**status, "state": "OFFLINE", "message": "No SUM session on this system: no SUM files found and SAPup_real is not running."}
            else:
                status = {**status, "state": "PROCESS_DEAD",
                          "message": f"SAPup_real is not running on the host. SUM has stopped. Last known phase: {status['phase_detail'] or 'unknown'}."}
        elif status["state"] == "RUNNING" and status.get("changed_at"):
            mins = su.minutes_between(status["changed_at"], await ssh.host_time(sysid))
            limit = su.hang_threshold(status["phase"])
            if mins is not None and mins >= limit:
                status = {**status, "state": "POSSIBLE_HANG",
                          "message": f"SUM may be stuck: no status change for {mins:.0f} minutes (limit for this phase {limit}). Last phase: {status['phase_detail']}."}
        tail = (await read(paths["sapup"], 40))[-3000:] if status["state"] == "ERROR" else ""
        return PollOut(**{k: v for k, v in status.items() if k in PollOut.model_fields}, log_tail=tail)
