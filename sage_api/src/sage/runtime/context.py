"""Replayable workflow context. Every task call is a stored step; after a restart the workflow is
re-run from the top and finished steps return their stored result. Workflow code must call
ctx.task / ctx.wait / ctx.snapshot in the same order every time (no branching on live data)."""
import json
from datetime import timedelta

from sage.runtime.errors import AmbiguousStep, RunCancelled, WaitTimeout, WorkflowSuspended
from sage.util import iso, parse_iso, utcnow


def delay_for(elapsed: float, schedule) -> int:
    for threshold, interval in schedule:
        if elapsed < threshold:
            return interval
    return schedule[-1][1]


class WorkflowContext:
    def __init__(self, *, db, audit, run_id, tool_call_id, workflow, actor, task_ctx, backoff, max_wait,
                 clock=utcnow, is_cancelled=None, emit=None):
        self._db, self._audit, self.run_id, self.tool_call_id = db, audit, run_id, tool_call_id
        self.workflow, self.actor, self.task_ctx = workflow, actor, task_ctx
        self._backoff, self._max_wait, self._clock = backoff, max_wait, clock
        self._is_cancelled, self._emit = is_cancelled, emit
        self._seq = 0

    async def _guard(self):
        if self._is_cancelled and await self._is_cancelled():
            raise RunCancelled()

    async def _row(self, seq, kind, attempt=0):
        return await self._db.fetchone(
            "SELECT * FROM tool_steps WHERE tool_call_id=? AND seq=? AND kind=? AND attempt=?",
            (self.tool_call_id, seq, kind, attempt))

    async def _event(self, name, seq, kind, status):
        if self._emit:
            await self._emit("tool_step", {"workflow": self.workflow, "task": name, "seq": seq, "kind": kind, "status": status})

    async def _exec(self, task_cls, data, seq, kind, attempt=0):
        row = await self._row(seq, kind, attempt)
        if row and row["status"] == "running" and not task_cls.idempotent:
            raise AmbiguousStep(f"Step '{task_cls.name}' was interrupted and changes SAP; check the system before retrying.")
        if row is None:
            step_id = await self._db.execute(
                "INSERT INTO tool_steps(tool_call_id,seq,kind,attempt,name,workflow,input,status,created_at) VALUES(?,?,?,?,?,?,?,'running',?)",
                (self.tool_call_id, seq, kind, attempt, task_cls.name, self.workflow, data.model_dump_json(), iso(self._clock())))
        else:
            step_id = row["id"]
        await self._event(task_cls.name, seq, kind, "running")
        try:
            out = await task_cls().run(self.task_ctx, data)
        except Exception as e:
            await self._db.execute("UPDATE tool_steps SET status='error', error=? WHERE id=?", (str(e), step_id))
            await self._audit.write("tool.step", self.actor, self.run_id,
                                    {"workflow": self.workflow, "task": task_cls.name, "seq": seq, "status": "error", "error": str(e)})
            await self._event(task_cls.name, seq, kind, "error")
            raise
        await self._db.execute("UPDATE tool_steps SET status='ok', output=? WHERE id=?", (out.model_dump_json(), step_id))
        await self._audit.write("tool.step", self.actor, self.run_id,
                                {"workflow": self.workflow, "task": task_cls.name, "seq": seq, "status": "ok",
                                 "input": json.loads(data.model_dump_json()), "output": json.loads(out.model_dump_json())})
        await self._event(task_cls.name, seq, kind, "ok")
        return out

    async def task(self, task_cls, data):
        self._seq += 1
        row = await self._row(self._seq, "task")
        if row and row["status"] == "ok":
            return task_cls.Output.model_validate_json(row["output"])
        await self._guard()
        return await self._exec(task_cls, data, self._seq, "task")

    async def snapshot(self, name, fn):
        """Read live config once per run; replays see the same value."""
        self._seq += 1
        row = await self._row(self._seq, "snap")
        if row and row["status"] == "ok":
            return json.loads(row["output"])
        value = await fn()
        await self._db.execute(
            "INSERT OR REPLACE INTO tool_steps(tool_call_id,seq,kind,attempt,name,workflow,input,output,status,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,'ok',?)",
            (self.tool_call_id, self._seq, "snap", 0, name, self.workflow, "{}", json.dumps(value), iso(self._clock())))
        return value

    async def wait(self, task_cls, data, until, *, backoff=None, max_wait=None):
        """Poll a read-only task. One poll per entry; if not done, raise WorkflowSuspended so the
        scheduler wakes this run later. No coroutine stays blocked in memory."""
        self._seq += 1
        seq, now = self._seq, self._clock()
        backoff, max_wait = backoff or self._backoff, max_wait or self._max_wait
        wrow = await self._row(seq, "wait")
        if wrow and wrow["status"] == "ok":
            return task_cls.Output.model_validate_json(wrow["output"])
        if wrow is None:
            state = {"started_at": iso(now), "polls": 0}
            await self._db.execute(
                "INSERT INTO tool_steps(tool_call_id,seq,kind,attempt,name,workflow,input,status,created_at) VALUES(?,?,'wait',0,?,?,?,'running',?)",
                (self.tool_call_id, seq, task_cls.name, self.workflow, json.dumps(state), iso(now)))
        else:
            state = json.loads(wrow["input"])
        started = parse_iso(state["started_at"])
        if (now - started).total_seconds() > max_wait:
            await self._db.execute("UPDATE tool_steps SET status='error', error='timed_out' WHERE tool_call_id=? AND seq=? AND kind='wait'",
                                   (self.tool_call_id, seq))
            raise WaitTimeout(f"Gave up waiting for '{task_cls.name}' after {int(max_wait)} s.")
        await self._guard()
        out = await self._exec(task_cls, data, seq, "poll", attempt=state["polls"])
        state["polls"] += 1
        if until(out):
            await self._db.execute("UPDATE tool_steps SET status='ok', input=?, output=? WHERE tool_call_id=? AND seq=? AND kind='wait'",
                                   (json.dumps(state), out.model_dump_json(), self.tool_call_id, seq))
            return out
        await self._db.execute("UPDATE tool_steps SET input=? WHERE tool_call_id=? AND seq=? AND kind='wait'",
                               (json.dumps(state), self.tool_call_id, seq))
        raise WorkflowSuspended(now + timedelta(seconds=delay_for((now - started).total_seconds(), backoff)))
