import json

import pytest

from tests.conftest import login_admin
from tests.test_health_setup import SYS, WfA, WfB, mk_system, prepare_ok


@pytest.fixture
def app_kwargs():
    return {"workflows": {"wf_a": WfA, "wf_b": WfB}}


CHECK = "/api/workflows/wf_a/systems/1/check"


def grant(fake, granted: dict[str, list[str]]):
    """The RFC account holds only these values: {field: [values]}, whatever the object."""
    fake.functions["SUSR_USER_AUTH_FOR_OBJ_GET"] = lambda **_: {"VALUES": [
        {"FIELD": f, "VON": v, "BIS": ""} for f, vs in granted.items() for v in vs]}


def scan(fake, rows, unresolved=()):
    fake.functions["ZFM_AUTH_REQ_LIST"] = lambda **p: {"ET_RETURN": [], "EV_JSON": json.dumps({
        "rows": [{"auth_object": o, "auth_field": f, "auth_values": v, "source": "STATIC", "depth": 1, "callee_path": "x"} for o, f, v in rows],
        "unresolved": list(unresolved)})}


async def coverage(client):
    await client.put("/api/workflows/wf_a/systems/1", json={"settings": {"default_variant": "V1"}})
    await client.post(CHECK)
    return (await client.get("/api/workflows/wf_a/systems/1/guide")).json()


def by_value(g):
    return {(r["object"], r["field"], r["value"]): r for r in g["auth_coverage"]["rows"]}


async def test_all_missing_authorizations_are_listed_at_once_not_one_blocker_at_a_time(client, fake_rfc):
    prepare_ok(fake_rfc)
    scan(fake_rfc, [("S_BTCH_JOB", "JOBACTION", "RELE"), ("S_BTCH_JOB", "JOBGROUP", "*"), ("S_DEVELOP", "ACTVT", "03"),
                    ("S_USER_GRP", "ACTVT", "02"), ("S_RFC", "ACTVT", "16")])
    grant(fake_rfc, {"RFC_TYPE": ["FUNC"], "RFC_NAME": ["*"], "ACTVT": ["16"], "TABLE": ["*"]})   # no JOBACTION, JOBGROUP; ACTVT only 16
    await mk_system(client)
    g = await coverage(client)
    rows = by_value(g)
    missing = sorted(k for k, r in rows.items() if r["status"] == "missing")
    assert missing == [("S_BTCH_JOB", "JOBACTION", "RELE"), ("S_BTCH_JOB", "JOBGROUP", "*"), ("S_DEVELOP", "ACTVT", "03"), ("S_USER_GRP", "ACTVT", "02")]
    assert rows[("S_RFC", "ACTVT", "16")]["status"] == "granted"
    assert rows[("S_BTCH_JOB", "JOBACTION", "RELE")]["source"] == "ZFM_T"          # which function module needs it
    step = next(s for s in g["steps"] if s["kind"] == "auth_coverage")
    assert step["status"] == "fail" and "4 missing" in step["message"]
    r = await client.post("/api/workflows/wf_a/systems/1/enable")
    assert r.status_code == 400 and "auth_coverage" in r.json()["detail"]            # missing values block enabling


async def test_granted_rows_pass_and_ranges_and_patterns_match(client, fake_rfc):
    prepare_ok(fake_rfc)
    scan(fake_rfc, [("S_X", "F1", "ABC"), ("S_X", "F2", "M"), ("S_X", "F3", "DUMMY")])
    fake_rfc.functions["SUSR_USER_AUTH_FOR_OBJ_GET"] = lambda **_: {"VALUES": [
        {"FIELD": "F1", "VON": "AB*", "BIS": ""}, {"FIELD": "F2", "VON": "A", "BIS": "Z"},
        {"FIELD": "RFC_TYPE", "VON": "FUNC", "BIS": ""}, {"FIELD": "RFC_NAME", "VON": "*", "BIS": ""},
        {"FIELD": "ACTVT", "VON": "*", "BIS": ""}, {"FIELD": "TABLE", "VON": "*", "BIS": ""}]}
    await mk_system(client)
    rows = by_value(await coverage(client))
    assert rows[("S_X", "F1", "ABC")]["status"] == "granted" and rows[("S_X", "F2", "M")]["status"] == "granted"
    assert ("S_X", "F3", "DUMMY") not in rows                                       # a DUMMY check needs nothing


async def test_run_time_values_unresolved_calls_and_unreadable_account_need_review(client, fake_rfc):
    prepare_ok(fake_rfc)
    scan(fake_rfc, [("S_USER_AGR", "ACT_GROUP", "<ROLE>")], unresolved=["CALL FUNCTION <LV_FM> (dynamic name)"])
    await mk_system(client)
    g = await coverage(client)
    rows = by_value(g)
    assert rows[("S_USER_AGR", "ACT_GROUP", "<ROLE>")]["status"] == "review"
    assert any(r["status"] == "review" and not r["object"] and "dynamic name" in r["value"] for r in g["auth_coverage"]["rows"])
    step = next(s for s in g["steps"] if s["kind"] == "auth_coverage")
    assert step["status"] == "warn"                                                 # review never blocks

    del fake_rfc.functions["SUSR_USER_AUTH_FOR_OBJ_GET"]                            # account values cannot be read
    await client.post(CHECK)
    g = (await client.get("/api/workflows/wf_a/systems/1/guide")).json()
    assert {r["status"] for r in g["auth_coverage"]["rows"] if r["object"] and r["object"] != "S_TABU_NAM"} <= {"unknown", "review"}


async def test_without_the_scan_function_the_static_values_are_still_checked_and_it_only_warns(client, fake_rfc):
    prepare_ok(fake_rfc)
    del fake_rfc.functions["ZFM_AUTH_REQ_LIST"]
    fake_rfc.tables["TFDIR"] = [{"FUNCNAME": "ZFM_T"}]                              # ZFM_AUTH_REQ_LIST not installed either
    await mk_system(client)
    g = await coverage(client)
    status = {s["key"] or s["kind"]: s["status"] for s in g["steps"] if s["kind"] in ("fm_exists", "auth_coverage")}
    assert status["ZFM_AUTH_REQ_LIST"] == "warn" and status["auth_coverage"] == "warn"
    assert by_value(g)[("S_RFC", "RFC_NAME", "ZFM_T")]["status"] == "granted"
    assert (await client.post("/api/workflows/wf_a/systems/1/enable")).status_code == 200   # a warning does not block enabling
