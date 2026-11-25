"""Email groups, the workflow-to-group rules, and the sending of state emails over SMTP (settings in the DB).

An email says only which workflow ran on which system, who asked, the state, and for a failure the error text. It never
contains workflow results, because groups may hold people outside Sage.

A rule sends instantly or collects the events into an hourly or daily digest. A result state that lasts (an ERROR that a
schedule keeps finding) is mailed when it appears and again as a reminder, if the workflow lists it in `reminder_states`."""
import asyncio
import hashlib
import json
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage

from sage.util import iso, parse_iso, utcnow

log = logging.getLogger("sage.email")
ADDRESS = re.compile(r"^[^@\s,;<>\"]{1,64}@[^@\s,;<>\"]{1,190}\.[^@\s,;<>\"]{2,24}$")
BASE_EVENTS = {"started": "Started", "waiting": "Waiting (a long run paused)", "completed": "Completed", "failed": "Failed", "cancelled": "Cancelled"}
MODES = ("instant", "hourly", "daily")


class EmailError(Exception):
    pass


def event_catalog(wf_cls) -> dict[str, str]:
    """Events a workflow can send for: the run states, and the result states the workflow declares."""
    out = dict(BASE_EVENTS)
    if not wf_cls.durable:
        out.pop("waiting")
    out.update({f"result:{s}": f"Result is {s}" for s in wf_cls.result_states})
    return out


def call_key(workflow: str, system_id, input_: dict) -> str:
    """Identifies "the same question": one workflow, system and input. Used to decide when a repeated state is a reminder."""
    return hashlib.sha1(f"{workflow}|{system_id}|{json.dumps(input_, sort_keys=True)}".encode()).hexdigest()[:16]


def _clean(text: str, limit: int) -> str:
    return re.sub(r"[\r\n\t]+", " ", str(text or "")).strip()[:limit]


def smtp_send(cfg: dict, msg: EmailMessage, recipients: list[str]) -> None:
    """Blocking. Run it in a thread."""
    host, port, security = cfg["email.smtp_host"], int(cfg["email.smtp_port"]), cfg["email.security"]
    ctx = ssl.create_default_context()
    smtp = smtplib.SMTP_SSL(host, port, timeout=20, context=ctx) if security == "ssl" else smtplib.SMTP(host, port, timeout=20)
    try:
        if security == "starttls":
            smtp.starttls(context=ctx)
        if cfg["email.smtp_user"]:
            smtp.login(cfg["email.smtp_user"], cfg["email.smtp_password"])
        smtp.send_message(msg, to_addrs=recipients)
    finally:
        try:
            smtp.quit()
        except smtplib.SMTPException:
            pass


class EmailService:
    def __init__(self, db, settings, audit, workflows, clock=utcnow, sender=smtp_send):
        self._db, self._settings, self._audit, self._workflows, self._clock, self._send = db, settings, audit, workflows, clock, sender
        self._tasks: set[asyncio.Task] = set()

    # ---- groups ----
    async def groups(self) -> list[dict]:
        return await self._db.fetchall(
            "SELECT g.id,g.name,g.description,(SELECT COUNT(*) FROM email_group_members m WHERE m.group_id=g.id) AS members,"
            "(SELECT COUNT(DISTINCT workflow) FROM workflow_notifications n WHERE n.group_id=g.id) AS workflows FROM email_groups g ORDER BY g.name")

    async def group(self, group_id) -> dict | None:
        g = await self._db.fetchone("SELECT id,name,description FROM email_groups WHERE id=?", (group_id,))
        if g:
            g["members"] = await self._db.fetchall("SELECT email,name FROM email_group_members WHERE group_id=? ORDER BY email", (group_id,))
        return g

    @staticmethod
    def _members(members: list[dict]) -> list[tuple[str, str]]:
        seen, out = set(), []
        for m in members:
            email, name = str(m.get("email", "")).strip().lower(), _clean(m.get("name", ""), 80)
            if not ADDRESS.match(email) or len(email) > 254:
                raise EmailError(f"'{m.get('email', '')}' is not a valid email address.")
            if email not in seen:
                seen.add(email)
                out.append((email, name))
        return out

    async def save_group(self, group_id, name, description, members, actor) -> int:
        name = _clean(name, 60)
        if not name:
            raise EmailError("The group needs a name.")
        people = self._members(members)
        async with self._db.tx() as t:
            clash = await t.fetchone("SELECT id FROM email_groups WHERE name=? COLLATE NOCASE", (name,))
            if clash and clash["id"] != group_id:
                raise EmailError("A group with this name already exists.")
            if group_id is None:
                group_id = await t.execute("INSERT INTO email_groups(name,description,created_by,created_at) VALUES(?,?,?,?)",
                                           (name, _clean(description, 300), actor, iso(self._clock())))
            else:
                await t.execute("UPDATE email_groups SET name=?, description=? WHERE id=?", (name, _clean(description, 300), group_id))
                await t.execute("DELETE FROM email_group_members WHERE group_id=?", (group_id,))
            for email, person in people:
                await t.execute("INSERT INTO email_group_members(group_id,email,name) VALUES(?,?,?)", (group_id, email, person))
        await self._audit.write("email.group_save", actor, detail={"group_id": group_id, "name": name, "members": len(people)})
        return group_id

    async def delete_group(self, group_id, actor):
        await self._db.execute("DELETE FROM email_groups WHERE id=?", (group_id,))          # members and rules go with it
        await self._db.execute("DELETE FROM email_digest WHERE group_id=?", (group_id,))
        await self._audit.write("email.group_delete", actor, detail={"group_id": group_id})

    # ---- rules: which groups get which events of a workflow, instantly or as a digest ----
    async def rules(self, workflow) -> list[dict]:
        rows = await self._db.fetchall("SELECT group_id,events,mode FROM workflow_notifications WHERE workflow=? ORDER BY group_id", (workflow,))
        return [{"group_id": r["group_id"], "events": json.loads(r["events"]), "mode": r["mode"]} for r in rows]

    async def set_rules(self, workflow, rules: list[dict], actor):
        allowed = event_catalog(self._workflows[workflow])
        clean = {}
        for r in rules:
            events = [e for e in r["events"] if e in allowed]
            if events:
                clean[int(r["group_id"])] = (events, r.get("mode") if r.get("mode") in MODES else "instant")
        async with self._db.tx() as t:
            await t.execute("DELETE FROM workflow_notifications WHERE workflow=?", (workflow,))
            for gid, (events, mode) in clean.items():
                if not await t.fetchone("SELECT id FROM email_groups WHERE id=?", (gid,)):
                    raise EmailError(f"Group {gid} does not exist.")
                await t.execute("INSERT INTO workflow_notifications(workflow,group_id,events,mode) VALUES(?,?,?,?)", (workflow, gid, json.dumps(events), mode))
        await self._audit.write("email.rules_save", actor, detail={"workflow": workflow, "rules": {str(k): {"events": v[0], "mode": v[1]} for k, v in clean.items()}})

    # ---- sending ----
    async def _config(self) -> dict | None:
        keys = ("email.enabled", "email.smtp_host", "email.smtp_port", "email.security", "email.smtp_user", "email.smtp_password", "email.from_address")
        cfg = {k: await self._settings.get(k) for k in keys}
        return cfg if cfg["email.enabled"] and cfg["email.smtp_host"] and cfg["email.from_address"] else None

    async def _deliver(self, subject, body, recipients: list[str]):
        cfg = await self._config()
        if cfg is None:
            raise EmailError("Email is off or incomplete. Set email.enabled, email.smtp_host and email.from_address in the settings.")
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = cfg["email.from_address"], cfg["email.from_address"], _clean(subject, 200)
        msg.set_content(body)
        await asyncio.to_thread(self._send, cfg, msg, recipients)               # the recipients are not in the headers (blind copy)

    async def send_test(self, to: str, actor):
        if not ADDRESS.match(to.strip()):
            raise EmailError("That is not a valid email address.")
        try:
            await self._deliver("[DXC Sage] Test email", "This is a test email from DXC Sage. Email notifications are set up correctly.", [to.strip()])
        except EmailError:
            raise
        except Exception as e:  # noqa: BLE001
            raise EmailError(f"Sending failed: {e}") from None
        await self._audit.write("email.test", actor, detail={})

    async def last_sent(self, key: str, event: str) -> str | None:
        """When the last email for this workflow question and event went out (a failed attempt does not count, so it is tried again)."""
        row = await self._db.fetchone("SELECT created_at FROM email_log WHERE key=? AND event=? AND status<>'failed' ORDER BY id DESC LIMIT 1", (key, event))
        return row["created_at"] if row else None

    def notify(self, *, workflow, event, tool_call_id, run_id, system="", actor="", detail="", key="", reminder_since=""):
        """Queue the emails of one event. Never raises and never blocks the run; a failure is logged and shown on the email page."""
        task = asyncio.create_task(self._notify(workflow, event, tool_call_id, run_id, system, actor, detail, key, reminder_since))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def idle(self):
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def _label(self, workflow, event, reminder_since=""):
        label = event_catalog(self._workflows[workflow]).get(event, event)
        return f"{label} (reminder: still in this state since {reminder_since})" if reminder_since else label

    async def _notify(self, workflow, event, tool_call_id, run_id, system, actor, detail, key, reminder_since):
        try:
            rows = await self._db.fetchall(
                "SELECT n.group_id,n.events,n.mode,g.name FROM workflow_notifications n JOIN email_groups g ON g.id=n.group_id WHERE n.workflow=?", (workflow,))
            hit = [r for r in rows if event in json.loads(r["events"])]
            if not hit:
                return
            label = self._label(workflow, event, reminder_since)
            for r in (r for r in hit if r["mode"] != "instant"):                      # digests: keep the event, the digest job sends it
                try:
                    await self._db.execute("INSERT INTO email_digest(group_id,mode,tool_call_id,event,workflow,system,actor,run_id,label,detail,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                           (r["group_id"], r["mode"], tool_call_id, event, workflow, system, actor, run_id, label, _clean(detail, 300), iso(self._clock())))
                except Exception:  # noqa: BLE001 - this event of this call is already waiting for the digest
                    pass
            instant = [r for r in hit if r["mode"] == "instant"]
            people = sorted({m["email"] for r in instant for m in await self._db.fetchall("SELECT email FROM email_group_members WHERE group_id=?", (r["group_id"],))})
            if not people:
                return
            try:
                await self._db.execute("INSERT INTO email_log(tool_call_id,run_id,workflow,event,groups,recipients,status,error,created_at,key) VALUES(?,?,?,?,?,?,'queued','',?,?)",
                                       (tool_call_id, run_id, workflow, event, ", ".join(r["name"] for r in instant), len(people), iso(self._clock()), key))
            except Exception:  # noqa: BLE001 - the same event of the same call was already sent (a restart replayed it)
                return
            body = "\n".join([f"Workflow: {workflow}", f"System: {system or '-'}", f"Requested by: {actor or '-'}", f"State: {label}", f"Run: {run_id}", f"Time: {iso(self._clock())}",
                              *([f"Detail: {_clean(detail, 500)}"] if detail else []), "", "This message states the state only. Open DXC Sage for the result."])
            subject = f"[DXC Sage] {'Reminder: ' if reminder_since else ''}{workflow} on {system or '-'}: {self._label(workflow, event)}"
            try:
                await self._deliver(subject, body, people)
                status, error = "sent", ""
            except Exception as e:  # noqa: BLE001
                status, error = "failed", _clean(str(e), 300)
                log.warning("email for %s %s failed: %s", workflow, event, error)
            await self._db.execute("UPDATE email_log SET status=?, error=? WHERE tool_call_id=? AND event=?", (status, error, tool_call_id, event))
            await self._audit.write("email.send", "system", run_id, {"workflow": workflow, "event": event, "groups": [r["name"] for r in instant], "recipients": len(people), "status": status})
        except Exception:  # noqa: BLE001
            log.exception("email notification crashed")

    # ---- digests ----
    async def _digest_due(self, group_id: int, mode: str, now) -> bool:
        row = await self._db.fetchone("SELECT last_sent_at FROM email_digest_state WHERE group_id=? AND mode=?", (group_id, mode))
        last = parse_iso(row["last_sent_at"]) if row else None
        if mode == "hourly":
            return last is None or (now - last).total_seconds() >= 3600
        hour = int(await self._settings.get("email.digest_hour_utc"))
        return now.hour >= hour and (last is None or last.date() < now.date())

    async def flush_digests(self):
        """Called by the scheduler tick. Sends one email per group and mode whose digest is due and has events. Never raises."""
        try:
            now = self._clock()
            for g in await self._db.fetchall("SELECT DISTINCT group_id, mode FROM email_digest"):
                if not await self._digest_due(g["group_id"], g["mode"], now):
                    continue
                rows = await self._db.fetchall("SELECT * FROM email_digest WHERE group_id=? AND mode=? ORDER BY id", (g["group_id"], g["mode"]))
                name = (await self._db.fetchone("SELECT name FROM email_groups WHERE id=?", (g["group_id"],)) or {"name": "?"})["name"]
                people = [m["email"] for m in await self._db.fetchall("SELECT email FROM email_group_members WHERE group_id=? ORDER BY email", (g["group_id"],))]
                if not people:
                    await self._db.execute("DELETE FROM email_digest WHERE group_id=? AND mode=?", (g["group_id"], g["mode"]))
                    continue
                lines = [f"{r['created_at']}  {r['workflow']} on {r['system'] or '-'}  {r['label']}  (requested by {r['actor'] or '-'})" + (f"\n    {r['detail']}" if r["detail"] else "") for r in rows]
                body = "\n".join([f"{len(rows)} event(s) for the group {name}:", "", *lines, "", "This message states the states only. Open DXC Sage for the results."])
                subject = f"[DXC Sage] {g['mode'].capitalize()} digest: {len(rows)} event(s) for {name}"
                try:
                    await self._deliver(subject, body, people)
                    status, error = "sent", ""
                except Exception as e:  # noqa: BLE001
                    status, error = "failed", _clean(str(e), 300)
                await self._db.execute("INSERT INTO email_log(tool_call_id,run_id,workflow,event,groups,recipients,status,error,created_at,key) VALUES(0,0,'(digest)',?,?,?,?,?,?,'')",
                                       (f"digest:{g['mode']}:{iso(now)}:{g['group_id']}", name, len(people), status, error, iso(now)))
                if status == "sent":                                                # a failed digest keeps its events and is tried again on the next tick
                    await self._db.execute("DELETE FROM email_digest WHERE group_id=? AND mode=? AND id<=?", (g["group_id"], g["mode"], rows[-1]["id"]))
                    await self._db.execute("INSERT INTO email_digest_state(group_id,mode,last_sent_at) VALUES(?,?,?) ON CONFLICT(group_id,mode) DO UPDATE SET last_sent_at=excluded.last_sent_at",
                                           (g["group_id"], g["mode"], iso(now)))
                    await self._audit.write("email.digest", "system", detail={"group": name, "mode": g["mode"], "events": len(rows), "recipients": len(people)})
        except Exception:  # noqa: BLE001
            log.exception("digest flush crashed")

    async def log(self, limit=50) -> list[dict]:
        return await self._db.fetchall("SELECT workflow,event,groups,recipients,status,error,created_at FROM email_log ORDER BY id DESC LIMIT ?", (limit,))
