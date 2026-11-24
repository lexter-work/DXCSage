"""A registered system is usable by a workflow only after an admin sets the workflow up on it."""
import json

from sage.util import iso, utcnow


class SetupError(Exception):
    pass


class AccessError(Exception):
    pass


class WorkflowSetupService:
    def __init__(self, db, audit, systems, health, workflows, settings, clock=utcnow):
        self._db, self._audit, self._systems, self._health = db, audit, systems, health
        self._workflows, self._settings, self._clock = workflows, settings, clock

    def _wf(self, name):
        if name not in self._workflows:
            raise SetupError("unknown_workflow")
        return self._workflows[name]

    async def setup(self, workflow, system_id, settings: dict, actor):
        wf = self._wf(workflow)
        system = await self._systems.get(system_id)
        if not system or system["status"] != "active":
            raise SetupError("system_not_active")
        allowed = {s.key for s in wf.binding_settings}
        clean = {k: v for k, v in settings.items() if k in allowed}
        now = iso(self._clock())
        await self._db.execute(
            "INSERT INTO workflow_systems(workflow,system_id,status,settings,created_at,updated_at) VALUES(?,?,'setup',?,?,?) "
            "ON CONFLICT(workflow,system_id) DO UPDATE SET settings=excluded.settings, updated_at=excluded.updated_at, "
            "status=CASE WHEN status='enabled' THEN 'enabled' ELSE 'setup' END",
            (workflow, system_id, json.dumps(clean), now, now))
        await self._audit.write("workflow.setup", actor, detail={"workflow": workflow, "system_id": system_id, "settings": clean})

    async def enable(self, workflow, system_id, actor):
        self._wf(workflow)
        row = await self._db.fetchone("SELECT * FROM workflow_systems WHERE workflow=? AND system_id=?", (workflow, system_id))
        if not row:
            raise SetupError("not_set_up")
        rows = await self._health.check(system_id, workflow, actor)
        bad = [f"{r['req_kind']}:{r['req_key']} {r['status']}" for r in rows if r["status"] in ("fail", "blocked")]
        if bad:
            raise SetupError("Cannot enable, failing requirements: " + "; ".join(bad))
        await self._db.execute("UPDATE workflow_systems SET status='enabled', enabled_by=?, updated_at=? WHERE id=?",
                               (actor, iso(self._clock()), row["id"]))
        await self._audit.write("workflow.enable", actor, detail={"workflow": workflow, "system_id": system_id})

    async def disable(self, workflow, system_id, actor):
        await self._db.execute("UPDATE workflow_systems SET status='disabled', updated_at=? WHERE workflow=? AND system_id=?",
                               (iso(self._clock()), workflow, system_id))
        await self._audit.write("workflow.disable", actor, detail={"workflow": workflow, "system_id": system_id})

    async def bindings(self, workflow) -> list[dict]:
        rows = await self._db.fetchall(
            "SELECT ws.system_id, s.label, s.sid, ws.status, ws.settings FROM workflow_systems ws "
            "JOIN systems s ON s.id=ws.system_id WHERE ws.workflow=? ORDER BY s.label", (workflow,))
        for r in rows:
            r["settings"] = json.loads(r["settings"])
            r["health"] = await self._health.overall(r["system_id"], workflow)
        return rows

    async def enabled_systems(self, workflow) -> list[dict]:
        """Systems offered to the model: enabled here, system active, last check pass or warn."""
        out = []
        for b in await self.bindings(workflow):
            sys_ = await self._systems.get(b["system_id"])
            if b["status"] == "enabled" and sys_["status"] == "active" and b["health"] in ("pass", "warn"):
                out.append(sys_)
        return out

    async def authorize_run(self, workflow, system_label, actor):
        if workflow in await self._settings.get("workflows.disabled"):
            raise AccessError(f"Workflow '{workflow}' is disabled.")
        system = await self._systems.by_label(system_label)
        row = system and await self._db.fetchone(
            "SELECT * FROM workflow_systems WHERE workflow=? AND system_id=?", (workflow, system["id"]))
        if not row or row["status"] != "enabled" or system["status"] != "active":
            raise AccessError(f"Workflow '{workflow}' is not enabled on system '{system_label}'.")
        health = await self._health.ensure_fresh(system["id"], workflow, actor)
        if health not in ("pass", "warn"):
            failed = [f"{r['req_kind']}:{r['req_key']}" for r in await self._health.latest(system["id"], workflow)
                      if r["status"] in ("fail", "blocked")]
            raise AccessError(f"Health check failed on '{system_label}': " + ", ".join(failed))
        return system, json.loads(row["settings"])
