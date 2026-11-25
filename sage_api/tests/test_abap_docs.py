import pytest

from sage.abap_docs import CATALOG, _load
from sage.workflows.sap_obsolete_tcodes import SapObsoleteTcodes
from sage.workflows.sap_readiness_check import SapReadinessCheck
from tests.test_health_setup import mk_system


@pytest.fixture
def app_kwargs():
    return {"workflows": {"sap_readiness_check": SapReadinessCheck}}


def test_every_object_of_the_workflow_is_documented_and_every_part_file_exists():
    assert {o for wf in (SapReadinessCheck, SapObsoleteTcodes) for o, _ in wf.abap_objects()} <= set(CATALOG)
    for doc in CATALOG.values():
        assert doc["flow"] and doc["create"]
        for part in doc["parts"]:
            assert _load(part["file"]).strip()


async def test_docs_show_the_system_name_and_need_admin(client):
    await mk_system(client)
    r = await client.put("/api/systems/1/abap-names", json={"object_id": "ZFM_RC_START_ANALYSIS", "name": "YFM_START"})
    assert r.status_code == 200
    lst = (await client.get("/api/abap-objects?system_id=1")).json()
    row = next(o for o in lst if o["object_id"] == "ZFM_RC_START_ANALYSIS")
    assert row["name"] == "YFM_START" and row["used_by"] == ["sap_readiness_check"] and lst[0]["kind"] == "function_group"
    d = (await client.get("/api/abap-objects/ZFM_RC_START_ANALYSIS?system_id=1")).json()
    assert "YFM_START" in d["create"][1]["text"] and d["parts"][0]["code"].strip()
    assert (await client.get("/api/abap-objects/NOPE")).status_code == 404
    client.cookies.clear()
    assert (await client.get("/api/abap-objects")).status_code in (401, 403)
