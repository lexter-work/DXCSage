"""Usage counts only; there are no limits."""
from sage.util import utcnow


class UsageService:
    def __init__(self, db, clock=utcnow):
        self._db, self._clock = db, clock

    async def record_run(self, run_id: int):
        run = await self._db.fetchone("SELECT * FROM runs WHERE id=?", (run_id,))
        wf = (await self._db.fetchone("SELECT COUNT(*) c FROM tool_calls WHERE run_id=?", (run_id,)))["c"]
        tasks = (await self._db.fetchone(
            "SELECT COUNT(*) c FROM tool_steps s JOIN tool_calls t ON t.id=s.tool_call_id "
            "WHERE t.run_id=? AND s.kind IN ('task','poll')", (run_id,)))["c"]
        day = self._clock().date().isoformat()
        await self._db.execute(
            "INSERT INTO usage_counters(user_id,day,requests,tokens_in,tokens_out,workflow_calls,task_calls) VALUES(?,?,1,?,?,?,?) "
            "ON CONFLICT(user_id,day) DO UPDATE SET requests=requests+1, tokens_in=tokens_in+excluded.tokens_in, "
            "tokens_out=tokens_out+excluded.tokens_out, workflow_calls=workflow_calls+excluded.workflow_calls, "
            "task_calls=task_calls+excluded.task_calls",
            (run["user_id"], day, run["tokens_in"], run["tokens_out"], wf, tasks))

    async def me(self, user_id: int) -> list[dict]:
        return await self._db.fetchall("SELECT * FROM usage_counters WHERE user_id=? ORDER BY day DESC", (user_id,))

    async def all(self) -> list[dict]:
        return await self._db.fetchall(
            "SELECT u.username, c.* FROM usage_counters c JOIN users u ON u.id=c.user_id ORDER BY c.day DESC, u.username")
