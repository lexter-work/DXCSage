from datetime import datetime, timedelta, timezone

import pytest
from pydantic import BaseModel

from sage.runtime.context import WorkflowContext, delay_for
from sage.runtime.errors import AmbiguousStep, WaitTimeout, WorkflowSuspended
from sage.tasks.base import Task, TaskContext


class In(BaseModel):
    n: int = 0


class Out(BaseModel):
    v: int


CALLS = {"write": 0, "poll": 0}


class WriteTask(Task):
    name, Input, Output, idempotent = "t.write", In, Out, False

    async def run(self, ctx, data):
        CALLS["write"] += 1
        return Out(v=1)


class PollTask(Task):
    name, Input, Output = "t.poll", In, Out

    async def run(self, ctx, data):
        CALLS["poll"] += 1
        return Out(v=CALLS["poll"])


class Clock:
    def __init__(self):
        self.t = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        return self.t


BACKOFF = [[60, 10], [300, 60]]


async def make(db, audit, clock, rfc, settings_store, tool_call_id=1):
    await db.execute("INSERT OR IGNORE INTO users(id,username,password_hash,role,created_at) VALUES(1,'u','x','user','t')")
    await db.execute("INSERT OR IGNORE INTO chats(id,user_id,title,provider,model,created_at) VALUES(1,1,'c','p','m','t')")
    await db.execute("INSERT OR IGNORE INTO runs(id,chat_id,user_id,provider,model,status,started_at) VALUES(1,1,1,'p','m','running','t')")
    await db.execute("INSERT OR IGNORE INTO tool_calls(id,run_id,provider_call_id,workflow,input,status,started_at) VALUES(1,1,'c1','wf','{}','running','t')")
    tc = TaskContext(system_id=1, rfc=rfc, settings=settings_store, binding={}, data_dir=None)
    return WorkflowContext(db=db, audit=audit, run_id=1, tool_call_id=tool_call_id, workflow="wf", actor="u",
                           task_ctx=tc, backoff=BACKOFF, max_wait=3600, clock=clock)


def test_delay_for():
    assert delay_for(5, BACKOFF) == 10 and delay_for(100, BACKOFF) == 60 and delay_for(9999, BACKOFF) == 60


async def test_task_is_memoized_on_replay(db, audit, rfc, settings_store):
    CALLS.update(write=0, poll=0)
    clock = Clock()
    ctx = await make(db, audit, clock, rfc, settings_store)
    assert (await ctx.task(WriteTask, In())).v == 1
    ctx2 = await make(db, audit, clock, rfc, settings_store)          # replay: new context, same tool_call
    assert (await ctx2.task(WriteTask, In())).v == 1
    assert CALLS["write"] == 1


async def test_interrupted_non_idempotent_step_is_ambiguous(db, audit, rfc, settings_store):
    clock = Clock()
    ctx = await make(db, audit, clock, rfc, settings_store)
    await db.execute("INSERT INTO tool_steps(tool_call_id,seq,kind,attempt,name,workflow,input,status,created_at) "
                     "VALUES(1,1,'task',0,'t.write','wf','{}','running','t')")
    with pytest.raises(AmbiguousStep):
        await ctx.task(WriteTask, In())


async def test_wait_suspends_resumes_and_never_repeats_earlier_steps(db, audit, rfc, settings_store):
    CALLS.update(write=0, poll=0)
    clock = Clock()
    result = None
    for round_ in range(3):                                           # 3 resumes, like 3 scheduler wake-ups
        ctx = await make(db, audit, clock, rfc, settings_store)
        await ctx.task(WriteTask, In())
        try:
            result = await ctx.wait(PollTask, In(), until=lambda o: o.v >= 3)
            break
        except WorkflowSuspended as s:
            assert s.resume_at == clock.t + timedelta(seconds=10)
            clock.t = s.resume_at
    assert result.v == 3 and CALLS == {"write": 1, "poll": 3}
    ctx = await make(db, audit, clock, rfc, settings_store)           # replay after completion: no new calls
    await ctx.task(WriteTask, In())
    assert (await ctx.wait(PollTask, In(), until=lambda o: True)).v == 3
    assert CALLS == {"write": 1, "poll": 3}


async def test_wait_times_out(db, audit, rfc, settings_store):
    CALLS.update(write=0, poll=0)
    clock = Clock()
    ctx = await make(db, audit, clock, rfc, settings_store)
    with pytest.raises(WorkflowSuspended):
        await ctx.wait(PollTask, In(), until=lambda o: False)
    clock.t += timedelta(seconds=4000)
    ctx = await make(db, audit, clock, rfc, settings_store)
    with pytest.raises(WaitTimeout):
        await ctx.wait(PollTask, In(), until=lambda o: False)


async def test_snapshot_is_stable_across_replay(db, audit, rfc, settings_store):
    clock = Clock()
    box = {"v": 1}

    async def read():
        return {"v": box["v"]}

    ctx = await make(db, audit, clock, rfc, settings_store)
    assert await ctx.snapshot("cfg", read) == {"v": 1}
    box["v"] = 2
    ctx2 = await make(db, audit, clock, rfc, settings_store)
    assert await ctx2.snapshot("cfg", read) == {"v": 1}
