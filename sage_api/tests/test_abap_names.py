import pytest

from tests.conftest import login_admin
from sage.workflows.sap_readiness_check import SapReadinessCheck
from tests.test_health_setup import SYS, WfA, WfB, mk_system, prepare_ok


@pytest.fixture
def app_kwargs():
    return {"workflows": {"wf_a": WfA, "wf_b": WfB, "sap_readiness_check": SapReadinessCheck}}


NAMES = "/api/systems/1/abap-names"


async def put(client, object_id, name):
    return await client.put(NAMES, json={"object_id": object_id, "name": name})


async def test_rfc_call_uses_the_system_name_and_unmapped_ids_pass_through(client, app, fake_rfc):
    await mk_system(client)
    seen = []
    fake_rfc.functions["YFM_STATUS"] = lambda **p: seen.append("renamed") or {"STATUS": "F"}
    fake_rfc.functions["ZFM_OTHER"] = lambda **p: seen.append("plain") or {}
    rfc = app.state.services.rfc
    await app.state.services.systems.set_abap_name(1, "ZFM_T", "yfm_status", "t", {"ZFM_T": "function_module"})
    await rfc.call(1, "ZFM_T")
    await rfc.call(1, "ZFM_OTHER")
    assert seen == ["renamed", "plain"]


async def test_health_checks_the_renamed_object_and_the_guide_keeps_the_id(client, fake_rfc):
    prepare_ok(fake_rfc)
    fake_rfc.tables["TFDIR"] = [{"FUNCNAME": "YFM_T"}]                           # this system only has the Y name
    await mk_system(client)
    await client.put("/api/workflows/wf_b/systems/1", json={"settings": {}})
    rows = (await client.post("/api/workflows/wf_b/systems/1/check")).json()
    assert next(r for r in rows if r["req_kind"] == "fm_exists")["status"] == "fail"   # ZFM_T does not exist here

    r = await put(client, "ZFM_T", "YFM_T")
    assert r.status_code == 200 and r.json()["names"] == {"ZFM_T": "YFM_T"}
    g = (await client.get("/api/workflows/wf_b/systems/1/guide")).json()
    step = next(s for s in g["steps"] if s["kind"] == "fm_exists")
    assert step["status"] == "pass"                                              # re-checked on rename, no manual step
    assert step["key"] == "ZFM_T" and step["name"] == "YFM_T" and "YFM_T (ID ZFM_T)" in step["title"]
    assert "YFM_T" in step["text"] and "ZFM_T" not in step["source_text"].replace("ZFM_CHECK_JOB_STATUS", "")
    assert ["S_RFC", "RFC_NAME", "YFM_T"] in g["auth_table"] and ["S_RFC", "RFC_NAME", "ZFM_T"] not in g["auth_table"]
    assert g["abap_objects"] == [{"object_id": "ZFM_T", "kind": "function_module", "name": "YFM_T"},
                                 {"object_id": "ZFM_AUTH_REQ_LIST", "kind": "function_module", "name": "ZFM_AUTH_REQ_LIST"},
                                 {"object_id": "ZFG_MCPARCHPH", "kind": "function_group", "name": "ZFG_MCPARCHPH"}]
    md = (await client.get("/api/workflows/wf_b/systems/1/guide?format=markdown")).text
    assert "YFM_T (ID ZFM_T)" in md


async def test_validation_reset_clash_and_admin_only(client, app, fake_rfc):
    await mk_system(client)
    assert (await put(client, "ZFM_NOPE", "YFM_X")).status_code == 400            # unknown ID
    assert (await put(client, "ZFM_T", "bad name!")).status_code == 400
    assert (await put(client, "ZFM_T", "1ABC")).status_code == 400                 # must start with a letter
    assert (await put(client, "ZFM_T", "A" * 31)).status_code == 400
    assert (await put(client, "ZFM_T", "/DXC/FM_T")).status_code == 200            # namespaced names are fine
    assert (await app.state.services.systems.abap_names(1)) == {"ZFM_T": "/DXC/FM_T"}
    assert (await put(client, "ZFM_T", "zfm_t")).json()["names"] == {}              # using the ID again removes the override
    assert (await put(client, "ZFM_T", "ZFM_RC_START_ANALYSIS")).status_code == 400  # clashes with another object's ID
    audit = await app.state.services.db.fetchall("SELECT detail FROM audit_log WHERE event='system.abap_name'")
    assert len(audit) == 2 and "/DXC/FM_T" in audit[0]["detail"]
    await client.post("/api/users", json={"username": "bob", "password": "bob-password-1", "role": "user"})
    await client.post("/api/auth/logout")
    await client.post("/api/auth/login", json={"username": "bob", "password": "bob-password-1"})
    assert (await put(client, "ZFM_T", "YFM_T")).status_code == 403
