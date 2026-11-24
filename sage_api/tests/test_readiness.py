from datetime import datetime, timezone

import pytest

from sage.runtime.context import WorkflowContext
from sage.runtime.errors import WorkflowFailed, WorkflowSuspended
from sage.tasks.base import TaskContext
from sage.workflows.sap_readiness_check import ReadinessInput, SapReadinessCheck


class Clock:
    def __init__(self):
        self.t = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        return self.t


def pad(n):
    return n.rjust(10, "0")


def sap_world(fake, *, missing=(), status_codes=("R", "F"), variants=("V1",)):
    notes = ["1668882", "2971435", "2758146", "2399707", "2903677", "2502552", "2781766"]
    have = [n for n in notes if n not in missing]
    fake.tables["CWBNTHEAD"], fake.lengths["CWBNTHEAD"] = [{"NUMM": pad(n)} for n in have], {"NUMM": 10}
    fake.tables["CWBNTCUST"] = [{"NUMM": pad(n), "PRSTATUS": "E"} for n in have]
    fake.lengths["CWBNTCUST"] = {"NUMM": 10, "PRSTATUS": 1}
    fake.tables["VARID"] = [{"REPORT": "RC_COLLECT_ANALYSIS_DATA", "VARIANT": v} for v in variants]
    fake.lengths["VARID"] = {"REPORT": 40, "VARIANT": 14}
    codes = iter(status_codes)
    last = {"c": status_codes[-1]}

    def job_status(**p):
        last["c"] = next(codes, last["c"])
        return {"STATUS": last["c"]}
    fake.functions["ZFM_CHECK_JOB_STATUS"] = job_status
    fake.functions["ZFM_RC_START_ANALYSIS"] = lambda **p: {"REAL_JOBNAME": p["JOBNAME"], "JOBCOUNT": "01234567"}
    fake.functions["ZFM_RC_FETCH_ANALYSIS"] = lambda **p: {"FILENAME": "rc.zip", "ZIP_DATA": b"PK\x03\x04data"}
    fake.functions["ZFM_RC_NOTES_DOWNLOAD"] = lambda **p: {"EV_SCHEDULE_ID": "S1", "EV_RUN_ID": "R1", "EV_JOB_COUNT": "01", "ET_RETURN": []}


async def make_ctx(db, audit, rfc, settings_store, tmp_path, clock, binding=None):
    await db.execute("INSERT OR IGNORE INTO users(id,username,password_hash,role,created_at) VALUES(1,'u','x','user','t')")
    await db.execute("INSERT OR IGNORE INTO chats(id,user_id,title,provider,model,created_at) VALUES(1,1,'c','p','m','t')")
    await db.execute("INSERT OR IGNORE INTO runs(id,chat_id,user_id,provider,model,status,started_at) VALUES(1,1,1,'p','m','running','t')")
    await db.execute("INSERT OR IGNORE INTO tool_calls(id,run_id,provider_call_id,workflow,input,status,started_at) VALUES(1,1,'c','sap_readiness_check','{}','running','t')")
    tc = TaskContext(1, rfc, settings_store, binding if binding is not None else {"default_variant": "V1"}, tmp_path, "TS3")
    return WorkflowContext(db=db, audit=audit, run_id=1, tool_call_id=1, workflow="sap_readiness_check", actor="u",
                           task_ctx=tc, backoff=[[60, 10], [300, 60]], max_wait=7200, clock=clock)


async def drive(db, audit, rfc, settings_store, tmp_path, clock, data, **kw):
    """Replay the workflow like the scheduler does, until it returns or fails."""
    for _ in range(20):
        ctx = await make_ctx(db, audit, rfc, settings_store, tmp_path, clock, **kw)
        try:
            return await SapReadinessCheck().run(ctx, data)
        except WorkflowSuspended as s:
            clock.t = s.resume_at
    raise AssertionError("did not finish")


async def test_happy_path_replays_without_rescheduling(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    sap_world(fake_rfc, status_codes=("R", "R", "F"))
    out = await drive(db, audit, rfc, settings_store, tmp_path, Clock(), ReadinessInput(system_name="TS3"))
    assert out.final_status == "finished" and out.filename == "rc.zip" and out.size_bytes == 8
    assert out.job_name == "RC_COLLECT_ANALYSIS_DATA" and out.job_count == "01234567"
    assert fake_rfc.count("ZFM_RC_START_ANALYSIS") == 1           # scheduled once despite replays
    assert (tmp_path / "downloads" / "TS3").exists()
    assert all(n.present and n.implemented for n in out.notes if not n.conditional)


async def test_missing_required_note_is_downloaded_then_proceeds(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    sap_world(fake_rfc, missing=("2903677",))
    orig = fake_rfc.functions["ZFM_RC_NOTES_DOWNLOAD"]

    def dl(**p):                                                   # the download makes the note appear
        fake_rfc.tables["CWBNTHEAD"].append({"NUMM": pad("2903677")})
        fake_rfc.tables["CWBNTCUST"].append({"NUMM": pad("2903677"), "PRSTATUS": "E"})
        return orig(**p)
    fake_rfc.functions["ZFM_RC_NOTES_DOWNLOAD"] = dl
    out = await drive(db, audit, rfc, settings_store, tmp_path, Clock(), ReadinessInput(system_name="TS3"))
    assert fake_rfc.count("ZFM_RC_NOTES_DOWNLOAD") == 1 and out.final_status == "finished"


async def test_note_never_arrives_fails_before_scheduling(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    sap_world(fake_rfc, missing=("2903677",))
    await settings_store.set("readiness.prerequisite_notes", {**(await settings_store.get("readiness.prerequisite_notes")),
                                                              "download_wait_seconds": 30, "download_poll_seconds": 10}, "t")
    with pytest.raises(WorkflowFailed, match="2903677"):
        await drive(db, audit, rfc, settings_store, tmp_path, Clock(), ReadinessInput(system_name="TS3"))
    assert fake_rfc.count("ZFM_RC_START_ANALYSIS") == 0


async def test_unknown_variant_and_no_variant_fail(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    sap_world(fake_rfc)
    with pytest.raises(WorkflowFailed, match="variant"):
        await drive(db, audit, rfc, settings_store, tmp_path, Clock(), ReadinessInput(system_name="TS3", variant_name="NOPE"))
    with pytest.raises(WorkflowFailed, match="variant"):
        await drive(db, audit, rfc, settings_store, tmp_path, Clock(), ReadinessInput(system_name="TS3"), binding={})


async def test_job_failure_reported(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    sap_world(fake_rfc, status_codes=("R", "A"))
    with pytest.raises(WorkflowFailed, match="aborted"):
        await drive(db, audit, rfc, settings_store, tmp_path, Clock(), ReadinessInput(system_name="TS3"))


def test_requirements_include_tables_fms_and_shared_tasks():
    keys = {(r.kind, r.key) for r in SapReadinessCheck.requirements()}
    assert {("table_readable", "CWBNTHEAD"), ("table_readable", "VARID"), ("fm_exists", "ZFM_RC_START_ANALYSIS"),
            ("fm_exists", "ZFM_CHECK_JOB_STATUS"), ("fm_authorized", "ZFM_RC_FETCH_ANALYSIS")} <= keys
