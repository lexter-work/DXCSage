"""Scheduled recurring runs of workflows. Admin-defined; no model is involved.

A schedule runs one workflow with a fixed input, as its creator, through the same code as a chat run (so authorization, the
health check, audit, steps and email notifications all apply). Only workflows that declare `schedulable` can be scheduled:
read-only ones. A workflow that changes SAP is never run unattended."""
import json
import re
from datetime import datetime, timedelta

from pydantic import ValidationError

from sage.util import iso, utcnow

MIN_MINUTES, MAX_MINUTES = 5, 10080
TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ScheduleError(Exception):
    pass


def next_after(kind: str, interval_minutes: int | None, at_time: str | None, now: datetime) -> datetime:
    """The next time at or after which a schedule is due, counted from `now` (UTC)."""
    if kind == "interval":
        return now + timedelta(minutes=interval_minutes or MIN_MINUTES)
    hh, mm = (int(x) for x in (at_time or "00:00").split(":"))
    due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return due if due > now else due + timedelta(days=1)


class ScheduleService:
    def __init__(self, db, audit, workflows, systems, clock=utcnow):
        self._db, self._audit, self._workflows, self._systems, self._clock = db, audit, workflows, systems, clock

    # ---- reading ----
    async def items(self) -> list[dict]:
        rows = await self._db.fetchall(
            "SELECT s.*, u.username AS created_by_name, "
            "(SELECT status FROM runs r WHERE r.id=s.last_run_id) AS last_run_status FROM schedules s JOIN users u ON u.id=s.created_by ORDER BY s.name")
        for r in rows:
            r["input"], r["enabled"] = json.loads(r["input"]), bool(r["enabled"])
        return rows

    async def get(self, schedule_id) -> dict | None:
        return next((r for r in await self.items() if r["id"] == schedule_id), None)

    async def active_run(self, schedule) -> bool:
        return bool(await self._db.fetchone("SELECT id FROM runs WHERE chat_id=? AND status IN ('running','waiting')", (schedule["chat_id"],)))

    async def due(self) -> list[dict]:
        now = iso(self._clock())
        return [s for s in await self.items() if s["enabled"] and s["next_run_at"] and s["next_run_at"] <= now]

    # ---- writing ----
    def _check(self, workflow, input_, kind, interval_minutes, at_time) -> dict:
        cls = self._workflows.get(workflow)
        if cls is None:
            raise ScheduleError("Unknown workflow.")
        if not cls.schedulable:
            raise ScheduleError(f"{workflow} cannot be scheduled: only read-only workflows can run unattended.")
        try:
            data = cls.Input.model_validate(input_)
        except ValidationError as e:
            raise ScheduleError(f"Invalid input: {e.errors(include_url=False)}") from None
        if kind == "interval":
            if not isinstance(interval_minutes, int) or not MIN_MINUTES <= interval_minutes <= MAX_MINUTES:
                raise ScheduleError(f"The interval must be between {MIN_MINUTES} minutes and {MAX_MINUTES // 1440} days.")
        elif kind == "daily":
            if not TIME.match(at_time or ""):
                raise ScheduleError("Give the time of day as HH:MM (UTC).")
        else:
            raise ScheduleError("The schedule is either every N minutes or daily.")
        return json.loads(data.model_dump_json())

    async def save(self, schedule_id, *, name, workflow, input, kind, interval_minutes=None, at_time=None, enabled=True, actor: dict) -> int:
        name = re.sub(r"\s+", " ", name or "").strip()[:60]
        if not name:
            raise ScheduleError("The schedule needs a name.")
        clean = self._check(workflow, input, kind, interval_minutes, at_time)
        if "system_name" in clean and not await self._systems.by_label(clean["system_name"]):
            raise ScheduleError(f"Unknown system '{clean['system_name']}'.")
        now = self._clock()
        nxt = iso(next_after(kind, interval_minutes, at_time, now)) if enabled else None
        fields = (name, workflow, json.dumps(clean), kind, interval_minutes if kind == "interval" else None, at_time if kind == "daily" else None, int(enabled), nxt)
        async with self._db.tx() as t:
            clash = await t.fetchone("SELECT id FROM schedules WHERE name=? COLLATE NOCASE", (name,))
            if clash and clash["id"] != schedule_id:
                raise ScheduleError("A schedule with this name already exists.")
            if schedule_id is None:
                chat = await t.execute("INSERT INTO chats(user_id,title,provider,model,created_at) VALUES(?,?,?,?,?)",
                                       (actor["id"], f"Schedule: {name}", "schedule", "-", iso(now)))
                schedule_id = await t.execute(
                    "INSERT INTO schedules(name,workflow,input,kind,interval_minutes,at_time,enabled,next_run_at,chat_id,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (*fields, chat, actor["id"], iso(now)))
            else:
                await t.execute("UPDATE schedules SET name=?, workflow=?, input=?, kind=?, interval_minutes=?, at_time=?, enabled=?, next_run_at=? WHERE id=?", (*fields, schedule_id))
                await t.execute("UPDATE chats SET title=? WHERE id=(SELECT chat_id FROM schedules WHERE id=?)", (f"Schedule: {name}", schedule_id))
        await self._audit.write("schedule.save", actor["username"], detail={"schedule_id": schedule_id, "name": name, "workflow": workflow, "input": clean,
                                                                           "kind": kind, "interval_minutes": interval_minutes, "at_time": at_time, "enabled": enabled})
        return schedule_id

    async def set_enabled(self, schedule_id, enabled: bool, actor: str):
        s = await self.get(schedule_id)
        nxt = iso(next_after(s["kind"], s["interval_minutes"], s["at_time"], self._clock())) if enabled else None
        await self._db.execute("UPDATE schedules SET enabled=?, next_run_at=? WHERE id=?", (int(enabled), nxt, schedule_id))
        await self._audit.write("schedule.enable" if enabled else "schedule.disable", actor, detail={"schedule_id": schedule_id})

    async def delete(self, schedule_id, actor: str):
        """Removes the schedule. Its past runs and their records stay."""
        await self._db.execute("DELETE FROM schedules WHERE id=?", (schedule_id,))
        await self._audit.write("schedule.delete", actor, detail={"schedule_id": schedule_id})

    async def triggered(self, schedule, run_id: int | None, advance: bool = True):
        """Records a start and, for a timed start, moves next_run_at on. A missed run (server was off) runs once, not once per missed slot."""
        now = self._clock()
        nxt = iso(next_after(schedule["kind"], schedule["interval_minutes"], schedule["at_time"], now)) if schedule["enabled"] else None
        await self._db.execute("UPDATE schedules SET next_run_at=?, last_run_at=?, last_run_id=COALESCE(?, last_run_id) WHERE id=?",
                               (nxt if advance else schedule["next_run_at"], iso(now) if run_id else schedule["last_run_at"], run_id, schedule["id"]))
