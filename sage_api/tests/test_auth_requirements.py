import json

import pytest
from pydantic import BaseModel

from sage.runtime.errors import WorkflowFailed
from sage.sap.requirements import FmAuthorized, FmExists
from sage.tasks.base import Task
from sage.workflows.base import SystemInput, Workflow
from sage.workflows.sap_auth_requirements import AuthReqInput, SapAuthRequirements
from sage.workflows.sap_readiness_check import SapReadinessCheck
from tests.test_readiness import Clock, make_ctx


class Empty(BaseModel):
    pass


class NewTask(Task):
    name, Input, Output = "t.new", Empty, Empty
    requirements = (FmExists("ZFM_NEW"), FmAuthorized("ZFM_NEW", group="ZFG_X"))


class NewWorkflow(Workflow):
    """Stands in for a workflow added later: nothing in sap_auth_requirements mentions it."""
    name, description, Input, Output, tasks = "new_wf", "x", SystemInput, Empty, (NewTask,)

    async def run(self, ctx, data):
        return Empty()


def scan(fake, calls):
    def fn(**p):
        calls.append(p["IV_FUNCNAME"])
        if p["IV_FUNCNAME"] == "ZFM_BAD":
            return {"ET_RETURN": [{"TYPE": "E", "MESSAGE": "boom"}], "EV_JSON": ""}
        return {"ET_RETURN": [], "EV_JSON": json.dumps({"rows": [
            {"auth_object": "S_X", "auth_field": "F", "auth_values": p["IV_FUNCNAME"], "source": "STATIC:A:1", "depth": 1, "callee_path": ""}],
            "unresolved": ["dynamic call"]})}
    fake.functions["ZFM_AUTH_REQ_LIST"] = fn


async def run(ctx_args, data, workflows):
    ctx = await make_ctx(*ctx_args)
    ctx.task_ctx.workflows = workflows
    return await SapAuthRequirements().run(ctx, data)


async def test_new_workflow_is_picked_up_and_each_function_module_scanned_once(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    calls = []
    scan(fake_rfc, calls)
    wfs = {"sap_readiness_check": SapReadinessCheck, "new_wf": NewWorkflow, "sap_auth_requirements": SapAuthRequirements}
    out = await run((db, audit, rfc, settings_store, tmp_path, Clock()), AuthReqInput(system_name="TS3"), wfs)
    by = {w.workflow: w for w in out.workflows}
    assert set(by) == set(wfs)
    assert any(v.object == "S_RFC" and v.value == "ZFM_NEW" for v in by["new_wf"].values)        # declared
    assert any(v.object == "S_X" and v.source == "ZFM_NEW" for v in by["new_wf"].values)         # scanned
    assert "ZFM_NEW: dynamic call" in by["new_wf"].unresolved
    assert len(calls) == len(set(calls))                                                         # shared FMs scanned once


async def test_filter_and_scan_failure_reported_not_fatal(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    scan(fake_rfc, [])

    class BadTask(NewTask):
        name = "t.bad"
        requirements = (FmExists("ZFM_BAD"),)

    class BadWf(NewWorkflow):
        name, tasks = "bad_wf", (BadTask,)

    wfs = {"new_wf": NewWorkflow, "bad_wf": BadWf}
    out = await run((db, audit, rfc, settings_store, tmp_path, Clock()), AuthReqInput(system_name="TS3", workflow="bad_wf"), wfs)
    assert [w.workflow for w in out.workflows] == ["bad_wf"] and "boom" in out.workflows[0].errors[0]


async def test_unknown_workflow_filter_fails(db, audit, rfc, settings_store, tmp_path):
    with pytest.raises(WorkflowFailed):
        await run((db, audit, rfc, settings_store, tmp_path, Clock()), AuthReqInput(system_name="TS3", workflow="nope"), {"new_wf": NewWorkflow})
