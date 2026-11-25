import json
from datetime import datetime, timezone

import pytest
from pydantic import BaseModel

from sage.providers.base import Done, Provider, TextDelta, ToolUse
from sage.tasks.base import Task
from sage.workflows.base import SystemInput, Workflow
from tests.conftest import login_admin


class Out(BaseModel):
    answer: str


class PollOut(BaseModel):
    n: int


class Polls(BaseModel):
    pass


COUNT = {"polls": 0}


class PollTask(Task):
    name, Input, Output = "t.poll", Polls, PollOut

    async def run(self, ctx, data):
        COUNT["polls"] += 1
        return PollOut(n=COUNT["polls"])


class SlowWf(Workflow):
    name, description, Input, Output, durable = "slow_wf", "waits for 3 polls", SystemInput, Out, True
    tasks = (PollTask,)

    async def run(self, ctx, data):
        r = await ctx.wait(PollTask, Polls(), until=lambda o: o.n >= 3)
        return Out(answer=f"done after {r.n}")


class QuickWf(Workflow):
    name, description, Input, Output = "quick_wf", "instant", SystemInput, Out

    async def run(self, ctx, data):
        return Out(answer="quick-ok")


class Script(Provider):
    """Scripted provider: each call plays the next turn."""
    name = "anthropic"

    def __init__(self, turns):
        self.turns, self.calls = list(turns), []

    async def stream(self, *, model, system, messages, tools, api_key, max_tokens):
        self.calls.append((messages, [t.name for t in tools]))
        for ev in self.turns.pop(0):
            yield ev

    async def list_models(self, api_key):
        return []


class Clock:
    def __init__(self):
        self.t = datetime(2026, 6, 1, tzinfo=timezone.utc)

    def __call__(self):
        return self.t


@pytest.fixture
def script():
    return Script([])


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def app_kwargs(script, clock):
    return {"workflows": {"slow_wf": SlowWf, "quick_wf": QuickWf}, "providers": {"anthropic": script}, "clock": clock}


async def setup_world(client, app, fake_rfc, workflows=("quick_wf",)):
    await login_admin(client)
    await client.post("/api/systems", json={"label": "TS3", "sid": "TS3", "ashost": "h", "sysnr": "00", "client": "100",
                                            "rfc_user": "U", "rfc_password": "pw-secret-1"})
    for w in workflows:
        await client.put(f"/api/workflows/{w}/systems/1", json={"settings": {}})
        assert (await client.post(f"/api/workflows/{w}/systems/1/enable")).status_code == 200
    await app.state.services.settings.set("providers.anthropic_api_key", "k", "t")
    return (await client.post("/api/chats", json={"title": "t", "provider": "anthropic", "model": "claude-sonnet-5-5"})).json()["id"]


async def run_to_end(client, app, chat_id, text="go"):
    run_id = (await client.post(f"/api/chats/{chat_id}/runs", json={"text": text})).json()["run_id"]
    await app.state.services.agent.drive(run_id)
    return run_id


async def status(app, run_id):
    return (await app.state.services.db.fetchone("SELECT * FROM runs WHERE id=?", (run_id,)))


async def test_tool_call_loop_persists_and_counts(client, app, script, fake_rfc):
    cid = await setup_world(client, app, fake_rfc)
    script.turns = [[TextDelta("checking"), ToolUse("c1", "quick_wf", {"system_name": "TS3"}), Done(10, 5)],
                    [TextDelta("all good"), Done(20, 7)]]
    run_id = await run_to_end(client, app, cid)
    r = await status(app, run_id)
    assert r["status"] == "done" and r["tokens_in"] == 30 and r["tokens_out"] == 12
    msgs = (await client.get(f"/api/chats/{cid}/messages")).json()
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert json.loads(msgs[2]["content"])[0]["content"].count("quick-ok") == 1
    assert script.calls[0][1] == ["quick_wf"]                        # model sees only enabled workflows, not tasks
    u = (await client.get("/api/usage/me")).json()
    assert u[0]["requests"] == 1 and u[0]["workflow_calls"] == 1 and u[0]["tokens_in"] == 30
    ev = (await app.state.services.db.fetchall("SELECT type FROM run_events WHERE run_id=?", (run_id,)))
    assert "tool_start" in {e["type"] for e in ev} and ev[-1]["type"] == "done"


async def test_workflow_not_enabled_is_refused_to_model(client, app, script, fake_rfc):
    cid = await setup_world(client, app, fake_rfc, workflows=())
    script.turns = [[ToolUse("c1", "quick_wf", {"system_name": "TS3"}), Done(1, 1)], [TextDelta("sorry"), Done(1, 1)]]
    run_id = await run_to_end(client, app, cid)
    msgs = (await client.get(f"/api/chats/{cid}/messages")).json()
    result = json.loads(msgs[2]["content"])[0]
    assert result["is_error"] is True and "not enabled" in result["content"]
    assert (await status(app, run_id))["status"] == "done"


async def test_max_turns_cap(client, app, script, fake_rfc):
    cid = await setup_world(client, app, fake_rfc)
    await app.state.services.settings.set("agent.max_turns", 2, "t")
    loop = [ToolUse("c%d" % i, "quick_wf", {"system_name": "TS3"}) for i in range(5)]
    script.turns = [[loop[i], Done(1, 1)] for i in range(5)]
    run_id = await run_to_end(client, app, cid)
    r = await status(app, run_id)
    assert r["status"] == "failed" and "max_turns" in r["error"]


async def test_chat_delete_keeps_records(client, app, script, fake_rfc):
    cid = await setup_world(client, app, fake_rfc)
    script.turns = [[ToolUse("c1", "quick_wf", {"system_name": "TS3"}), Done(1, 1)], [TextDelta("x"), Done(1, 1)]]
    run_id = await run_to_end(client, app, cid)
    assert (await client.delete(f"/api/chats/{cid}")).status_code == 200
    assert (await client.get("/api/chats")).json() == []
    db = app.state.services.db
    assert (await db.fetchone("SELECT COUNT(*) c FROM runs WHERE id=?", (run_id,)))["c"] == 1
    assert (await db.fetchone("SELECT COUNT(*) c FROM tool_calls WHERE run_id=?", (run_id,)))["c"] == 1
    assert (await db.fetchone("SELECT COUNT(*) c FROM audit_log WHERE event='chat.delete'"))["c"] == 1
    assert (await client.post(f"/api/chats/{cid}/runs", json={"text": "again"})).status_code == 404


async def test_durable_run_waits_survives_restart_and_completes(client, app, script, fake_rfc, clock):
    COUNT["polls"] = 0
    cid = await setup_world(client, app, fake_rfc, workflows=("slow_wf",))
    script.turns = [[ToolUse("c1", "slow_wf", {"system_name": "TS3"}), Done(1, 1)], [TextDelta("finished"), Done(1, 1)]]
    run_id = await run_to_end(client, app, cid)
    r = await status(app, run_id)
    assert r["status"] == "waiting" and r["resume_at"]
    agent = app.state.services.agent
    for _ in range(5):                                                # simulate restart + scheduler wake-ups
        r = await status(app, run_id)
        if r["status"] != "waiting":
            break
        clock.t = datetime.fromisoformat(r["resume_at"])
        await agent.recover_on_startup()
        await agent.drive(run_id)
    r = await status(app, run_id)
    assert r["status"] == "done" and COUNT["polls"] == 3
    msgs = (await client.get(f"/api/chats/{cid}/messages")).json()
    assert "done after 3" in json.loads(msgs[2]["content"])[0]["content"]


async def test_cancel_waiting_run(client, app, script, fake_rfc):
    COUNT["polls"] = 0
    cid = await setup_world(client, app, fake_rfc, workflows=("slow_wf",))
    script.turns = [[ToolUse("c1", "slow_wf", {"system_name": "TS3"}), Done(1, 1)]]
    run_id = await run_to_end(client, app, cid)
    assert (await client.post(f"/api/runs/{run_id}/cancel")).status_code == 200
    assert (await status(app, run_id))["status"] == "cancelled"
    tc = await app.state.services.db.fetchone("SELECT status FROM tool_calls WHERE run_id=?", (run_id,))
    assert tc["status"] == "cancelled"


async def test_non_durable_running_run_fails_on_startup_recovery(client, app, script, fake_rfc):
    cid = await setup_world(client, app, fake_rfc)
    db = app.state.services.db
    await db.execute("INSERT INTO runs(id,chat_id,user_id,provider,model,status,started_at) VALUES(99,?,1,'anthropic','m','running','t')", (cid,))
    await app.state.services.agent.recover_on_startup()
    r = await status(app, 99)
    assert r["status"] == "failed" and "restart" in r["error"]


async def test_users_cannot_touch_other_users_chats(client, app, script, fake_rfc):
    cid = await setup_world(client, app, fake_rfc)
    await client.post("/api/users", json={"username": "bob", "password": "bob-password-1", "role": "user"})
    await client.post("/api/auth/logout")
    await client.post("/api/auth/login", json={"username": "bob", "password": "bob-password-1"})
    assert (await client.get(f"/api/chats/{cid}/messages")).status_code == 404
    assert (await client.post(f"/api/chats/{cid}/runs", json={"text": "x"})).status_code == 404


async def test_own_run_info_has_steps_system_and_no_payloads(client, app, script, fake_rfc):
    cid = await setup_world(client, app, fake_rfc)
    script.turns = [[ToolUse("c1", "quick_wf", {"system_name": "TS3"}), Done(3, 4)], [TextDelta("ok"), Done(1, 1)]]
    run_id = await run_to_end(client, app, cid)
    info = (await client.get(f"/api/runs/{run_id}")).json()
    assert info["run"]["status"] == "done" and info["run"]["tokens_in"] == 4
    call = info["tool_calls"][0]
    assert call["workflow"] == "quick_wf" and call["system"]["label"] == "TS3" and call["steps"] == []
    assert "input" not in call and "output" not in call
    ev = await client.get(f"/api/runs/{run_id}/events")
    assert '"ts"' in ev.text
    await client.post("/api/auth/logout")
    await client.post("/api/auth/login", json={"username": "admin", "password": "admin-pass-12345"})
    assert (await client.get("/api/runs/9999")).status_code == 404
