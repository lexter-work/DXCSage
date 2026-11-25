import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import BaseModel

from sage.runtime.errors import WorkflowFailed
from sage.schedules import next_after
from sage.workflows.base import SystemInput, Workflow
from tests.conftest import login_admin
from tests.test_agent import Clock, Out, PollTask, Polls, Script
from tests.test_email import StateOut

SENT: list = []
COUNT = {"quick": 0}


class QuickRead(Workflow):
    name, description, Input, Output, schedulable = "quick_read", "instant, read-only", SystemInput, Out, True

    async def run(self, ctx, data):
        COUNT["quick"] += 1
        return Out(answer="quick-ok")


class SlowRead(Workflow):
    name, description, Input, Output, durable, schedulable = "slow_read", "waits", SystemInput, Out, True, True
    tasks = (PollTask,)

    async def run(self, ctx, data):
        r = await ctx.wait(PollTask, Polls(), until=lambda o: o.n % 3 == 0)
        return Out(answer=f"done {r.n}")


class BoomRead(Workflow):
    name, description, Input, Output, schedulable = "boom_read", "fails", SystemInput, Out, True

    async def run(self, ctx, data):
        raise WorkflowFailed("the system said no")


class StatusRead(Workflow):
    name, description, Input, Output, schedulable = "status_read", "reports ERROR", SystemInput, StateOut, True
    result_states = ("OK", "ERROR")

    @classmethod
    def result_state(cls, output):
        return output.state

    async def run(self, ctx, data):
        return StateOut(state="ERROR", message="still broken")


class WriteWf(Workflow):
    name, description, Input, Output = "write_wf", "changes SAP", SystemInput, Out

    async def run(self, ctx, data):
        return Out(answer="changed")


def sender(cfg, msg, recipients):
    SENT.append((msg, recipients))


@pytest.fixture(autouse=True)
def clear():
    SENT.clear()
    COUNT["quick"] = 0


@pytest.fixture
def clock():
    c = Clock()
    c.t = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
    return c


@pytest.fixture
def app_kwargs(clock):
    wfs = {w.name: w for w in (QuickRead, SlowRead, BoomRead, StatusRead, WriteWf)}
    return {"workflows": wfs, "providers": {"anthropic": Script([])}, "clock": clock, "mail_sender": sender}


async def world(client, app, workflows=("quick_read",)):
    await login_admin(client)
    await client.post("/api/systems", json={"label": "TS3", "sid": "TS3", "ashost": "h", "sysnr": "00", "client": "100", "rfc_user": "U", "rfc_password": "pw-secret-1"})
    for w in workflows:
        await client.put(f"/api/workflows/{w}/systems/1", json={"settings": {}})
        assert (await client.post(f"/api/workflows/{w}/systems/1/enable")).status_code == 200


def body(workflow="quick_read", **kw):
    return {"name": kw.pop("name", f"{workflow} every 10"), "workflow": workflow, "input": {"system_name": "TS3"}, "kind": "interval", "interval_minutes": 10, **kw}


async def tick(app, clock, minutes=0):
    clock.t += timedelta(minutes=minutes)
    agent = app.state.services.agent
    await agent._tick()
    while agent._tasks:
        await asyncio.gather(*list(agent._tasks.values()), return_exceptions=True)
    await app.state.services.email.idle()


async def runs(app):
    return await app.state.services.db.fetchall("SELECT * FROM runs WHERE provider='schedule' ORDER BY id")


def test_next_after():
    now = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
    assert next_after("interval", 10, None, now) == now + timedelta(minutes=10)
    assert next_after("daily", None, "09:30", now) == now.replace(hour=9, minute=30)
    assert next_after("daily", None, "07:00", now) == now.replace(hour=7) + timedelta(days=1)


async def test_only_valid_read_only_schedules_are_accepted(client, app):
    await world(client, app, ("quick_read", "write_wf"))
    assert (await client.post("/api/schedules", json=body("write_wf"))).status_code == 400                     # changes SAP: never unattended
    for bad in ({"interval_minutes": 1}, {"interval_minutes": 99999}, {"kind": "daily", "at_time": "25:00"}, {"input": {"system_name": "NOPE"}}, {"input": {}}):
        assert (await client.post("/api/schedules", json={**body(), **bad})).status_code == 400, bad
    ok = await client.post("/api/schedules", json=body())
    assert ok.status_code == 200 and ok.json()["next_run_at"].startswith("2026-06-01T08:10")
    assert (await client.post("/api/schedules", json=body())).status_code == 400                                # name taken
    assert (await client.get("/api/chats")).json() == []                                                         # the hidden chat is not in the chat list


async def test_due_schedule_runs_the_workflow_once_and_moves_on(client, app, clock):
    await world(client, app)
    sid = (await client.post("/api/schedules", json=body())).json()["id"]
    await tick(app, clock, 5)
    assert COUNT["quick"] == 0                                                                                  # not due yet
    await tick(app, clock, 6)
    assert COUNT["quick"] == 1
    r = (await runs(app))[0]
    assert r["status"] == "done" and r["tokens_in"] == 0
    s = (await client.get("/api/schedules")).json()[0]
    assert s["last_run_status"] == "done" and s["last_run_id"] == r["id"] and s["next_run_at"].startswith("2026-06-01T08:21")
    call = await app.state.services.db.fetchone("SELECT * FROM tool_calls WHERE run_id=?", (r["id"],))
    assert call["workflow"] == "quick_read" and "quick-ok" in call["output"]
    assert (await app.state.services.db.fetchall("SELECT * FROM usage_counters")) == []                         # not a user request
    await client.post(f"/api/schedules/{sid}/enabled", json={"enabled": False})
    await tick(app, clock, 60)
    assert COUNT["quick"] == 1                                                                                  # disabled: no run


async def test_overlap_is_skipped_and_a_long_run_resumes_until_done(client, app, clock):
    await world(client, app, ("slow_read",))
    await client.post("/api/schedules", json=body("slow_read"))
    await tick(app, clock, 11)
    first = (await runs(app))
    assert len(first) == 1 and first[0]["status"] == "waiting"
    await tick(app, clock, 11)                                                                                   # due again while the first still waits
    assert len(await runs(app)) == 1
    for _ in range(40):
        if (await runs(app))[0]["status"] == "done":
            break
        await tick(app, clock, 2)
    assert (await runs(app))[0]["status"] == "done"


async def test_failed_run_is_recorded_and_run_now_keeps_the_timetable(client, app, clock):
    await world(client, app, ("boom_read",))
    sid = (await client.post("/api/schedules", json=body("boom_read"))).json()["id"]
    before = (await client.get("/api/schedules")).json()[0]["next_run_at"]
    assert (await client.post(f"/api/schedules/{sid}/run")).status_code == 200
    await tick(app, clock)
    r = (await runs(app))[0]
    assert r["status"] == "failed" and "the system said no" in r["error"]
    after = (await client.get("/api/schedules")).json()[0]
    assert after["next_run_at"] == before and after["last_run_status"] == "failed"
    assert (await client.delete(f"/api/schedules/{sid}")).status_code == 200
    assert len(await runs(app)) == 1                                                                             # the run record stays


async def test_a_repeated_result_state_is_mailed_only_when_it_first_appears(client, app, clock):
    await world(client, app, ("status_read",))
    gid = (await client.post("/api/email/groups", json={"name": "Basis", "members": [{"email": "ops@vendor.io"}]})).json()["id"]
    await client.put("/api/workflows/status_read/notifications", json={"rules": [{"group_id": gid, "events": ["result:ERROR"]}]})
    s = app.state.services.settings
    for k, v in (("email.enabled", True), ("email.smtp_host", "smtp.example.com"), ("email.from_address", "sage@example.com")):
        await s.set(k, v, "t")
    await client.post("/api/schedules", json=body("status_read"))
    for _ in range(3):
        await tick(app, clock, 11)
    assert len(await runs(app)) == 3 and len(SENT) == 1                                                          # three runs, one email
    assert "schedule:status_read every 10" in SENT[0][0].get_content()
