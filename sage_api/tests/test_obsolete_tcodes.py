import pytest

from sage.runtime.errors import WorkflowFailed, WorkflowSuspended
from sage.tasks.su25_obsolete_tcodes import parse_lines
from sage.workflows.base import SystemInput
from sage.workflows.sap_obsolete_tcodes import SapObsoleteTcodes
from tests.test_readiness import Clock, make_ctx

ROW = "|        |{role:<30}|{desc:<28}|   3|Transaction                        |{tcode:<20}|{adj:<25}|     |       X      |      |        |"
GONE = "Old entry will be deleted"


def line(role, tcode, adj=GONE):
    return ROW.format(role=role, desc="Some role", tcode=tcode, adj=adj)


def test_parser_keeps_only_rows_flagged_for_deletion():
    rows = parse_lines([line("z_role_a", "SU01"), line("Z_ROLE_B", "SE16", adj=""), "| header |", "", line("Z_ROLE_B", "va01")])
    assert [(r["role"], r["tcode"]) for r in rows] == [("Z_ROLE_A", "SU01"), ("Z_ROLE_B", "VA01")]


def world(fake, lines, codes=("R", "F")):
    it = iter(codes)
    last = {"c": codes[-1]}

    def status(**p):
        last["c"] = next(it, last["c"])
        return {"STATUS": last["c"]}
    fake.functions["ZFM_CHECK_JOB_STATUS"] = status
    fake.functions["ZFM_RR_TC_OBS_START"] = lambda **p: {"REAL_JOBNAME": p["JOBNAME"], "JOBCOUNT": "00112233"}
    fake.functions["ZFM_RR_TC_OBS_FETCH"] = lambda **p: {"SPOOLNUM": "629858", "LISTLINES": [{"LINE": x} for x in lines]}


async def drive(db, audit, rfc, settings_store, tmp_path, clock):
    for _ in range(20):
        ctx = await make_ctx(db, audit, rfc, settings_store, tmp_path, clock)
        try:
            return await SapObsoleteTcodes().run(ctx, SystemInput(system_name="TS3"))
        except WorkflowSuspended as s:
            clock.t = s.resume_at
    raise AssertionError("did not finish")


async def test_scan_runs_once_waits_for_the_job_and_writes_a_csv(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    world(fake_rfc, [line("Z_A", "SU01"), line("Z_A", "SE16"), line("Z_B", "SU01")], codes=("R", "R", "F"))
    out = await drive(db, audit, rfc, settings_store, tmp_path, Clock())
    assert (out.total, out.roles, out.note) == (3, 2, "") and out.job_count == "00112233"
    assert fake_rfc.count("ZFM_RR_TC_OBS_START") == 1                    # scheduled once despite replays
    assert "Z_B,SU01" in open(out.file_path, encoding="utf-8").read()


async def test_empty_result_is_reported_with_a_hint_and_failed_job_fails(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    world(fake_rfc, ["| nothing |"], codes=("F",))
    out = await drive(db, audit, rfc, settings_store, tmp_path, Clock())
    assert out.total == 0 and "S_USER_AGR" in out.note and out.file_path == ""


async def test_failed_job_fails_the_run(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    world(fake_rfc, [], codes=("A",))
    with pytest.raises(WorkflowFailed):
        await drive(db, audit, rfc, settings_store, tmp_path, Clock())


def test_declared_authorizations_are_part_of_the_requirements():
    reqs = SapObsoleteTcodes.requirements()
    assert ("auth_declared", "PROFGEN_CORR_REPORT_2") in [(r.kind, r.key) for r in reqs]
    assert reqs[-1].kind == "auth_coverage"
    assert ("S_USER_AGR", "ACTVT", "03") in [row for r in reqs for row in r.auth_rows()]
