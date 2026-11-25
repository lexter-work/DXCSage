import pytest
from pydantic import BaseModel

from sage.providers.base import Done, ToolUse
from sage.runtime.errors import WorkflowFailed
from sage.workflows.base import SystemInput, Workflow
from tests.conftest import login_admin
from tests.test_agent import Clock, Out, QuickWf, Script, SlowWf, run_to_end, setup_world

SENT: list = []


class FailWf(Workflow):
    name, description, Input, Output = "fail_wf", "always fails", SystemInput, Out

    async def run(self, ctx, data):
        raise WorkflowFailed("the system said no")


class StateOut(BaseModel):
    state: str
    message: str


class StatusWf(Workflow):
    name, description, Input, Output = "status_wf", "reports a state", SystemInput, StateOut
    result_states = ("OK", "ERROR")

    @classmethod
    def result_state(cls, output):
        return output.state

    async def run(self, ctx, data):
        return StateOut(state="ERROR", message="SUM stopped")


def sender(cfg, msg, recipients):
    if cfg["email.smtp_host"] == "broken":
        raise OSError("connection refused")
    SENT.append((msg, recipients))


@pytest.fixture(autouse=True)
def clear():
    SENT.clear()


@pytest.fixture
def script():
    return Script([])


@pytest.fixture
def app_kwargs(script):
    return {"workflows": {"quick_wf": QuickWf, "slow_wf": SlowWf, "fail_wf": FailWf, "status_wf": StatusWf}, "providers": {"anthropic": script},
            "clock": Clock(), "mail_sender": sender}


async def configure(app, host="smtp.example.com"):
    s = app.state.services.settings
    for k, v in (("email.enabled", True), ("email.smtp_host", host), ("email.from_address", "sage@example.com")):
        await s.set(k, v, "t")


GROUP = {"name": "Basis team", "description": "on call", "members": [{"email": "Ana@Example.com", "name": "Ana"}, {"email": "ana@example.com"},
                                                                        {"email": "outsider@vendor.io", "name": "Vendor"}]}


async def group(client, body=GROUP):
    r = await client.post("/api/email/groups", json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def tag(client, workflow, gid, events):
    r = await client.put(f"/api/workflows/{workflow}/notifications", json={"rules": [{"group_id": gid, "events": events}]})
    assert r.status_code == 200, r.text
    return r.json()


async def test_groups_hold_outside_addresses_validated_and_deduplicated(client):
    await login_admin(client)
    g = await group(client)
    assert [m["email"] for m in g["members"]] == ["ana@example.com", "outsider@vendor.io"]
    for bad in ("not-an-email", "a@b", "x@y.com\nBcc: z@y.com", "a b@c.com"):
        r = await client.post("/api/email/groups", json={"name": "bad", "members": [{"email": bad}]})
        assert r.status_code == 400, bad
    assert (await client.post("/api/email/groups", json={**GROUP, "name": "basis TEAM"})).status_code == 400          # name taken, any case
    g2 = (await client.put(f"/api/email/groups/{g['id']}", json={"name": "Basis", "members": [{"email": "new@x.org"}]})).json()
    assert g2["name"] == "Basis" and [m["email"] for m in g2["members"]] == ["new@x.org"]
    assert (await client.get("/api/email/groups")).json()[0]["members"] == 1


async def test_rules_accept_only_events_the_workflow_has_and_vanish_with_the_group(client):
    await login_admin(client)
    gid = (await group(client))["id"]
    ev = {e["key"] for e in (await client.get("/api/workflows/quick_wf/notifications")).json()["events"]}
    assert ev == {"started", "completed", "failed", "cancelled"}                                         # not durable, so no waiting event
    assert "waiting" in {e["key"] for e in (await client.get("/api/workflows/slow_wf/notifications")).json()["events"]}
    assert "result:ERROR" in {e["key"] for e in (await client.get("/api/workflows/status_wf/notifications")).json()["events"]}
    rules = await tag(client, "quick_wf", gid, ["completed", "waiting", "bogus"])
    assert rules["rules"] == [{"group_id": gid, "events": ["completed"]}]
    assert (await client.put("/api/workflows/quick_wf/notifications", json={"rules": [{"group_id": 99, "events": ["completed"]}]})).status_code == 400
    await client.delete(f"/api/email/groups/{gid}")
    assert (await client.get("/api/workflows/quick_wf/notifications")).json()["rules"] == []


async def test_run_sends_state_emails_without_results_and_without_exposing_recipients(client, app, script, fake_rfc):
    cid = await setup_world(client, app, fake_rfc)
    await configure(app)
    gid = (await group(client))["id"]
    await tag(client, "quick_wf", gid, ["started", "completed"])
    script.turns = [[ToolUse("c1", "quick_wf", {"system_name": "TS3"}), Done(1, 1)], [Done(1, 1)]]
    await run_to_end(client, app, cid)
    await app.state.services.email.idle()
    assert [m["Subject"] for m, _ in SENT] == ["[DXC Sage] quick_wf on TS3: Started", "[DXC Sage] quick_wf on TS3: Completed"]
    msg, to = SENT[1]
    assert to == ["ana@example.com", "outsider@vendor.io"] and "outsider" not in str(msg["To"]) and "quick-ok" not in msg.get_content()
    assert "Requested by: admin" in msg.get_content()
    log = (await client.get("/api/email/log")).json()
    assert {r["status"] for r in log} == {"sent"} and log[0]["recipients"] == 2


async def test_failed_run_mails_the_error_and_a_replayed_event_is_not_sent_twice(client, app, script, fake_rfc):
    cid = await setup_world(client, app, fake_rfc, workflows=("fail_wf",))
    await configure(app)
    gid = (await group(client))["id"]
    await tag(client, "fail_wf", gid, ["failed"])
    script.turns = [[ToolUse("c1", "fail_wf", {"system_name": "TS3"}), Done(1, 1)], [Done(1, 1)]]
    await run_to_end(client, app, cid)
    email = app.state.services.email
    await email.idle()
    assert len(SENT) == 1 and "the system said no" in SENT[0][0].get_content() and SENT[0][0]["Subject"].endswith("Failed")
    call = await app.state.services.db.fetchone("SELECT id,run_id FROM tool_calls")
    email.notify(workflow="fail_wf", event="failed", tool_call_id=call["id"], run_id=call["run_id"])
    await email.idle()
    assert len(SENT) == 1


async def test_result_state_event_and_untagged_workflows_send_nothing(client, app, script, fake_rfc):
    cid = await setup_world(client, app, fake_rfc, workflows=("status_wf", "quick_wf"))
    await configure(app)
    gid = (await group(client))["id"]
    await tag(client, "status_wf", gid, ["result:ERROR"])
    script.turns = [[ToolUse("c1", "status_wf", {"system_name": "TS3"}), ToolUse("c2", "quick_wf", {"system_name": "TS3"}), Done(1, 1)], [Done(1, 1)]]
    await run_to_end(client, app, cid)
    await app.state.services.email.idle()
    assert [m["Subject"] for m, _ in SENT] == ["[DXC Sage] status_wf on TS3: Result is ERROR"] and "SUM stopped" in SENT[0][0].get_content()


async def test_smtp_failure_or_email_off_is_logged_and_never_breaks_the_run(client, app, script, fake_rfc):
    cid = await setup_world(client, app, fake_rfc)
    gid = (await group(client))["id"]
    await tag(client, "quick_wf", gid, ["completed", "started"])
    script.turns = [[ToolUse("c1", "quick_wf", {"system_name": "TS3"}), Done(1, 1)], [Done(1, 1)]]
    run_id = await run_to_end(client, app, cid)                                    # email is off by default
    await app.state.services.email.idle()
    st = (await app.state.services.db.fetchone("SELECT status FROM runs WHERE id=?", (run_id,)))["status"]
    log = (await client.get("/api/email/log")).json()
    assert st == "done" and {r["status"] for r in log} == {"failed"} and "Email is off" in log[0]["error"]
    assert (await client.get("/api/email/status")).json() == {"ready": False}
    await configure(app, host="broken")
    r = await client.post("/api/email/test", json={"to": "me@example.com"})
    assert r.status_code == 400 and "connection refused" in r.json()["detail"]


async def test_test_email_goes_to_the_given_address(client, app):
    await login_admin(client)
    await configure(app)
    assert (await client.post("/api/email/test", json={"to": "me@example.com"})).status_code == 200
    assert SENT[0][1] == ["me@example.com"] and (await client.get("/api/email/status")).json() == {"ready": True}
    assert (await client.post("/api/email/test", json={"to": "nope"})).status_code == 400
