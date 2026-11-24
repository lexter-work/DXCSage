import pytest
from pydantic import BaseModel

from sage.sap.requirements import FmAuthorized, FmExists, SettingPresent, TableReadable
from sage.sap.rfc import RfcError
from sage.tasks.base import Task
from sage.workflows.base import SettingSpec, SystemInput, Workflow
from tests.conftest import login_admin


class Empty(BaseModel):
    pass


class UseTable(Task):
    name, Input, Output = "t.use", Empty, Empty
    requirements = (FmExists("ZFM_T", guide="Create ZFM_T in SE37 (remote-enabled).", source="ZFM_CHECK_JOB_STATUS.txt"),
                    FmAuthorized("ZFM_T"))

    async def run(self, ctx, data):
        return Empty()


class WfA(Workflow):
    name, description, Input, Output = "wf_a", "A", SystemInput, Empty
    tasks = (UseTable,)
    extra_requirements = (TableReadable("T1", guide="Allow reading T1."),
                          SettingPresent("default_variant", level="warn", guide="Set a default variant."))
    binding_settings = (SettingSpec(key="default_variant", label="Default variant"),)

    async def run(self, ctx, data):
        return Empty()


class WfB(Workflow):
    name, description, Input, Output = "wf_b", "B", SystemInput, Empty
    tasks = (UseTable,)

    async def run(self, ctx, data):
        return Empty()


@pytest.fixture
def app_kwargs():
    return {"workflows": {"wf_a": WfA, "wf_b": WfB}}


SYS = {"label": "TS3", "sid": "TS3", "description": "", "ashost": "h", "sysnr": "00", "client": "100",
       "rfc_user": "RFCU", "rfc_password": "pw-secret-1"}


def prepare_ok(fake):
    fake.tables["TFDIR"], fake.lengths["TFDIR"] = [{"FUNCNAME": "ZFM_T"}], {"FUNCNAME": 30}
    fake.tables["T1"], fake.lengths["T1"] = [{"A": "1"}], {"A": 5}
    fake.functions["SUSR_USER_AUTH_FOR_OBJ_GET"] = lambda **_: {"VALUES": [
        {"FIELD": "RFC_TYPE", "VON": "FUNC", "BIS": ""}, {"FIELD": "RFC_NAME", "VON": "*", "BIS": ""},
        {"FIELD": "ACTVT", "VON": "16", "BIS": ""}]}


async def mk_system(client):
    await login_admin(client)
    await client.post("/api/systems", json=SYS)


def test_shared_task_requirements_deduped_per_workflow():
    keys = [(r.kind, r.key) for r in WfA.requirements()]
    assert keys == [("reachable", ""), ("login", ""), ("fm_exists", "ZFM_T"), ("fm_authorized", "ZFM_T"),
                    ("table_readable", "T1"), ("setting", "default_variant")]
    assert [(r.kind, r.key) for r in WfB.requirements()][-2:] == [("fm_exists", "ZFM_T"), ("fm_authorized", "ZFM_T")]


async def test_setup_check_enable_flow(client, fake_rfc):
    prepare_ok(fake_rfc)
    await mk_system(client)
    assert (await client.put("/api/workflows/wf_a/systems/1", json={"settings": {"default_variant": "V1"}})).status_code == 200
    rows = (await client.post("/api/workflows/wf_a/systems/1/check")).json()
    assert {r["status"] for r in rows} == {"pass"}
    assert (await client.post("/api/workflows/wf_a/systems/1/enable")).status_code == 200
    wf = {w["name"]: w for w in (await client.get("/api/workflows")).json()}
    assert wf["wf_a"]["bindings"][0]["status"] == "enabled" and wf["wf_b"]["bindings"] == []


async def test_enable_refused_when_requirement_fails(client, fake_rfc):
    prepare_ok(fake_rfc)
    del fake_rfc.tables["T1"]                                         # TableReadable fails
    await mk_system(client)
    await client.put("/api/workflows/wf_a/systems/1", json={"settings": {}})
    r = await client.post("/api/workflows/wf_a/systems/1/enable")
    assert r.status_code == 400 and "table_readable" in r.json()["detail"]


async def test_unreachable_blocks_dependents_and_never_calls_write_fms(client, fake_rfc, app):
    prepare_ok(fake_rfc)
    await mk_system(client)
    await client.put("/api/workflows/wf_b/systems/1", json={"settings": {}})
    orig = fake_rfc.call

    def down(fm, **p):
        if fm == "RFC_PING":
            raise RfcError("CONNECT", "no route")
        return orig(fm, **p)
    fake_rfc.call = down
    app.state.services.rfc.drop(1)
    rows = (await client.post("/api/workflows/wf_b/systems/1/check")).json()
    st = {r["req_kind"]: r["status"] for r in rows}
    assert st["reachable"] == "fail" and st["login"] == "blocked" and st["fm_exists"] == "blocked"
    assert all(f == "RFC_PING" or f.startswith(("RFC_READ", "SUSR")) for f, _ in fake_rfc.calls)


async def test_run_authorization_requires_enabled_and_passing(client, fake_rfc, app):
    prepare_ok(fake_rfc)
    await mk_system(client)
    setup = app.state.services.setup
    from sage.workflow_setup import AccessError
    with pytest.raises(AccessError):
        await setup.authorize_run("wf_b", "TS3", "alice")             # not set up
    await client.put("/api/workflows/wf_b/systems/1", json={"settings": {}})
    with pytest.raises(AccessError):
        await setup.authorize_run("wf_b", "TS3", "alice")             # set up, not enabled
    await client.post("/api/workflows/wf_b/systems/1/enable")
    system, binding = await setup.authorize_run("wf_b", "TS3", "alice")
    assert system["label"] == "TS3" and binding == {}


async def test_guide_lists_steps_with_status_and_combined_auth_table(client, fake_rfc):
    prepare_ok(fake_rfc)
    await mk_system(client)
    await client.put("/api/workflows/wf_a/systems/1", json={"settings": {}})
    await client.post("/api/workflows/wf_a/systems/1/check")
    g = (await client.get("/api/workflows/wf_a/systems/1/guide")).json()
    step = next(s for s in g["steps"] if s["kind"] == "fm_exists")
    assert step["status"] == "pass" and "SE37" in step["text"] and "ZFM_CHECK_JOB_STATUS" in step["source_text"]
    assert ["S_RFC", "RFC_NAME", "ZFM_T"] in g["auth_table"] and g["system"]["rfc_user"] == "RFCU"
    md = (await client.get("/api/workflows/wf_a/systems/1/guide?format=markdown")).text
    assert "S_RFC" in md and "TS3" in md
