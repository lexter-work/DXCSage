from sage.runtime.context import WorkflowContext
from sage.sap import sum as su
from sage.sap.ssh import SapSsh, SshParams
from sage.tasks.base import TaskContext
from sage.workflows.base import SystemInput
from sage.workflows.sap_sum_status import SapSumStatus
from tests.test_readiness import Clock

XML = "/usr/sap/TS3/SUM/abap/doc/analysis/SUMOBSERVER.XML"
SAPUP, STAT = "/usr/sap/TS3/SUM/abap/log/SAPup.log", "/usr/sap/TS3/SUM/abap/log/SAPupStat.log"


def observer(status="slp.task.state.RUNNING", changed="20260101115000", leaf="CREATE_MODSTATS", msg="", progress="42.5", others="slp.task.state.OK"):
    return f"""<SUM><estimate left="03:10:00">20260101153000</estimate>
<Task><id>SUM4ABAP</id><technicalName>SAPup</technicalName><status>{others}</status><progress>{progress}</progress></Task>
<Task><id>PREP_PARSETUP</id><parent>SUM4ABAP</parent><status>{others}</status></Task>
<Task><id>{leaf}</id><parent>PREP_PARSETUP</parent><status>{status}</status><statusChangedAt>{changed}</statusChangedAt>
<progressMessages><ProgressMessage><message>{msg}</message></ProgressMessage></progressMessages></Task></SUM>"""


async def run(db, audit, rfc, settings_store, tmp_path, fake_ssh):
    async def load(_):
        return SshParams("h", 22, fake_ssh.user, "password", fake_ssh.secret, fake_ssh.host_key_line)
    ssh = SapSsh(load, fake_ssh.connector, fake_ssh.host_key)
    await db.execute("INSERT OR IGNORE INTO users(id,username,password_hash,role,created_at) VALUES(1,'u','x','user','t')")
    await db.execute("INSERT OR IGNORE INTO chats(id,user_id,title,provider,model,created_at) VALUES(1,1,'c','p','m','t')")
    await db.execute("INSERT OR IGNORE INTO runs(id,chat_id,user_id,provider,model,status,started_at) VALUES(1,1,1,'p','m','running','t')")
    await db.execute("INSERT OR IGNORE INTO tool_calls(id,run_id,provider_call_id,workflow,input,status,started_at) VALUES(1,1,'c','sap_sum_status','{}','running','t')")
    tc = TaskContext(1, rfc, settings_store, {}, tmp_path, "TS3", ssh, sid="TS3")
    ctx = WorkflowContext(db=db, audit=audit, run_id=1, tool_call_id=1, workflow="sap_sum_status", actor="u", task_ctx=tc,
                          backoff=[[60, 10]], max_wait=7200, clock=Clock())
    return await SapSumStatus().run(ctx, SystemInput(system_name="TS3"))


def test_parser_phase_progress_and_detail():
    r = su.parse_observer_xml(observer())
    assert (r["state"], r["phase"], r["progress_pct"], r["time_remaining"]) == ("RUNNING", "Extraction", 42.5, "03:10:00")
    assert r["phase_detail"] == "PREP_PARSETUP/CREATE_MODSTATS"
    d = su.parse_observer_xml(observer("slp.task.state.DIALOG", leaf="ArchiveMissing"))
    assert d["state"] == "WAITING_INPUT" and su.required_action(d["state"], d["task_id"], d["message"], d["phase_detail"]).startswith("One or more required SAR")
    assert su.parse_observer_xml("not xml") is None and su.parse_observer_xml("<a/>") is None


def test_log_fallback_and_diagnosis():
    r = su.parse_logs("x\nTask is in running state\n", "55.5% LEFT: 01:00 END: 05:50:01 | Processes: total=2")
    assert (r["state"], r["progress_pct"], r["eta"]) == ("RUNNING", 55.5, "05:50:01")
    assert su.diagnose("ORA-01653: unable to extend table")["error_code"] == "TABLESPACE_FULL" and su.diagnose("all fine") is None


async def test_running_waiting_and_hang(db, audit, rfc, settings_store, fake_ssh, tmp_path):
    fake_ssh.files[XML], fake_ssh.running = observer(), {"SAPup_real"}
    out = await run(db, audit, rfc, settings_store, tmp_path, fake_ssh)
    assert (out.state, out.phase, out.source) == ("RUNNING", "Extraction", "xml") and out.required_action.startswith("Running normally")
    assert all(c.split()[0] in ("tail", "pgrep", "date") for c in fake_ssh.commands)           # fixed read-only commands only


async def test_stale_running_task_is_a_possible_hang(db, audit, rfc, settings_store, fake_ssh, tmp_path):
    fake_ssh.files[XML], fake_ssh.running = observer(changed="20260101090000"), {"SAPup_real"}      # 3 h silent, limit for Extraction is 30 min
    assert (await run(db, audit, rfc, settings_store, tmp_path, fake_ssh)).state == "POSSIBLE_HANG"


async def test_dead_process_offline_and_error_diagnosis(db, audit, rfc, settings_store, fake_ssh, tmp_path):
    fake_ssh.files[XML] = observer()                                                                  # SAPup_real not running
    assert (await run(db, audit, rfc, settings_store, tmp_path, fake_ssh)).state == "PROCESS_DEAD"


async def test_offline_when_no_files_and_no_process(db, audit, rfc, settings_store, fake_ssh, tmp_path):
    out = await run(db, audit, rfc, settings_store, tmp_path, fake_ssh)
    assert out.state == "OFFLINE" and out.source == "none"


async def test_error_state_is_diagnosed_from_the_log_tail(db, audit, rfc, settings_store, fake_ssh, tmp_path):
    fake_ssh.files[XML] = observer("slp.task.state.ERROR", msg="step failed", others="slp.task.state.ERROR")
    fake_ssh.files[SAPUP] = "line\nORA-01653: unable to extend table SAPSR3.X by 128 in tablespace PSAPSR3\n"
    out = await run(db, audit, rfc, settings_store, tmp_path, fake_ssh)
    assert out.state == "ERROR" and out.diagnosis.error_code == "TABLESPACE_FULL" and "TABLESPACE_FULL" in out.required_action
    fake_ssh.files[SAPUP] = "nothing known here"
