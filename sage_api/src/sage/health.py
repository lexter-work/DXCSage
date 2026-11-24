"""Per system and workflow health checks. Read-only; results stored in system_health."""
import json
from datetime import timedelta

from sage.sap.requirements import CheckEnv
from sage.sap.rfc import RfcError
from sage.util import iso, parse_iso, utcnow


class HealthService:
    def __init__(self, db, audit, rfc, systems, settings, workflows, clock=utcnow):
        self._db, self._audit, self._rfc, self._systems = db, audit, rfc, systems
        self._settings, self._workflows, self._clock = settings, workflows, clock

    async def check(self, system_id, workflow, actor, binding=None) -> list[dict]:
        system = await self._systems.get(system_id)
        if binding is None:
            row = await self._db.fetchone("SELECT settings FROM workflow_systems WHERE workflow=? AND system_id=?", (workflow, system_id))
            binding = json.loads(row["settings"]) if row else {}
        ping_error = None
        try:
            await self._rfc.ping(system_id)
        except RfcError as e:
            ping_error = e
        env = CheckEnv(self._rfc, system_id, system["rfc_user"], binding, self._settings, ping_error)
        reqs = self._workflows[workflow].requirements()
        now, out = iso(self._clock()), []
        blocked = ping_error is not None
        for r in reqs:
            if blocked and r.kind not in ("reachable", "login"):
                res_status, msg = "blocked", "system not reachable or login failed"
            else:
                res = await r.check(env)
                res_status, msg = res.status, res.message
            out.append({"system_id": system_id, "workflow": workflow, "req_kind": r.kind, "req_key": r.key,
                        "status": res_status, "message": msg, "checked_at": now})
        async with self._db.tx() as t:
            await t.execute("DELETE FROM system_health WHERE system_id=? AND workflow=?", (system_id, workflow))
            for o in out:
                await t.execute("INSERT INTO system_health(system_id,workflow,req_kind,req_key,status,message,checked_at) VALUES(?,?,?,?,?,?,?)",
                                (o["system_id"], o["workflow"], o["req_kind"], o["req_key"], o["status"], o["message"], now))
        await self._audit.write("system.health_check", actor, detail={
            "system_id": system_id, "workflow": workflow, "statuses": {f"{o['req_kind']}:{o['req_key']}": o["status"] for o in out}})
        return out

    async def latest(self, system_id, workflow) -> list[dict]:
        return await self._db.fetchall("SELECT * FROM system_health WHERE system_id=? AND workflow=? ORDER BY id", (system_id, workflow))

    @staticmethod
    def _overall(rows) -> str:
        if not rows:
            return "unknown"
        st = {r["status"] for r in rows}
        return "fail" if st & {"fail", "blocked"} else "warn" if "warn" in st else "pass"

    async def overall(self, system_id, workflow) -> str:
        return self._overall(await self.latest(system_id, workflow))

    async def ensure_fresh(self, system_id, workflow, actor) -> str:
        rows = await self.latest(system_id, workflow)
        max_age = int(await self._settings.get("health.max_age"))
        if not rows or self._clock() - parse_iso(rows[0]["checked_at"]) > timedelta(seconds=max_age):
            rows = await self.check(system_id, workflow, actor)
        return self._overall(rows)
