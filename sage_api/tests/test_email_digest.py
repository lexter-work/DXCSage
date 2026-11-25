import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from sage.db import Database
from sage.workflows.sap_obsolete_tcodes import SapObsoleteTcodes
from sage.workflows.sap_readiness_check import SapReadinessCheck
from sage.workflows.sap_sum_status import SapSumStatus
from tests.test_agent import Out, Script
from tests.test_email import SENT, sender
from tests.test_schedules import QuickRead, StatusRead, body, clear, clock, runs, tick, world  # noqa: F401 - fixtures and helpers
from sage.workflows.base import SystemInput, Workflow


@pytest.fixture(autouse=True)
def clear_mail():
    SENT.clear()


class RemindRead(StatusRead):
    name, reminder_states = "remind_read", ("ERROR",)


class HeavyRead(Workflow):
    name, description, Input, Output, schedulable, schedule_min_minutes = "heavy_read", "starts a job", SystemInput, Out, True, 1440

    async def run(self, ctx, data):
        return Out(answer="x")


@pytest.fixture
def app_kwargs(clock):
    wfs = {w.name: w for w in (QuickRead, RemindRead, HeavyRead)}
    return {"workflows": wfs, "providers": {"anthropic": Script([])}, "clock": clock, "mail_sender": sender}


async def mail_setup(client, app, workflow, events, mode="instant"):
    s = app.state.services.settings
    for k, v in (("email.enabled", True), ("email.smtp_host", "smtp.example.com"), ("email.from_address", "sage@example.com")):
        await s.set(k, v, "t")
    gid = (await client.post("/api/email/groups", json={"name": "Basis", "members": [{"email": "ops@vendor.io"}]})).json()["id"]
    r = await client.put(f"/api/workflows/{workflow}/notifications", json={"rules": [{"group_id": gid, "events": events, "mode": mode}]})
    assert r.status_code == 200 and r.json()["rules"][0]["mode"] == mode
    return gid


async def test_a_lasting_error_is_mailed_again_only_after_the_reminder_time(client, app, clock):
    await world(client, app, ("remind_read",))
    await mail_setup(client, app, "remind_read", ["result:ERROR"])
    await client.post("/api/schedules", json=body("remind_read"))
    for _ in range(6):                                                       # minutes 11 .. 66 after the start: the mail at 11, nothing yet for 55 minutes
        await tick(app, clock, 11)
    assert len(SENT) == 1 and "Reminder" not in SENT[0][0]["Subject"]
    await tick(app, clock, 11)                                               # minute 77: 66 minutes after the first mail
    assert len(SENT) == 2 and SENT[1][0]["Subject"].startswith("[DXC Sage] Reminder: remind_read")
    assert "still in this state since" in SENT[1][0].get_content()
    await app.state.services.settings.set("email.reminder_minutes", 0, "t")
    for _ in range(8):
        await tick(app, clock, 11)
    assert len(SENT) == 2                                                    # reminders off


async def test_workflows_without_reminder_states_do_not_repeat(client, app, clock):
    await world(client, app, ("quick_read",))
    assert QuickRead.reminder_states == () and SapSumStatus.reminder_states == ("ERROR", "POSSIBLE_HANG")


async def test_hourly_digest_collects_events_into_one_email(client, app, clock):
    await world(client, app, ("quick_read",))
    await mail_setup(client, app, "quick_read", ["completed"], mode="hourly")
    await client.post("/api/schedules", json=body("quick_read"))
    for _ in range(8):
        await tick(app, clock, 11)                                          # runs at 11, 22, .. 88
    digests = [m for m, _ in SENT]
    assert len(digests) == 2 and all("digest" in m["Subject"] for m in digests)
    assert "1 event(s)" in digests[0]["Subject"] and "6 event(s)" in digests[1]["Subject"]
    assert "quick_read on TS3" in digests[1].get_content() and "quick-ok" not in digests[1].get_content()
    assert SENT[0][1] == ["ops@vendor.io"]


async def test_daily_digest_waits_for_the_hour_and_sends_once_a_day(client, app, clock):
    await world(client, app, ("quick_read",))
    await mail_setup(client, app, "quick_read", ["completed"], mode="daily")
    email = app.state.services.email
    clock.t = datetime(2026, 6, 1, 6, 0, tzinfo=timezone.utc)
    for call in (1, 2):
        email.notify(workflow="quick_read", event="completed", tool_call_id=call, run_id=1, system="TS3", actor="admin")
    await email.idle()
    await email.flush_digests()
    assert SENT == []                                                        # before 08:00 UTC
    clock.t = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    await email.flush_digests()
    assert len(SENT) == 1 and "Daily digest: 2 event(s)" in SENT[0][0]["Subject"]
    email.notify(workflow="quick_read", event="completed", tool_call_id=3, run_id=1, system="TS3", actor="admin")
    await email.idle()
    await email.flush_digests()
    assert len(SENT) == 1                                                    # already sent today
    clock.t += timedelta(days=1)
    await email.flush_digests()
    assert len(SENT) == 2 and "1 event(s)" in SENT[1][0]["Subject"]


async def test_a_failed_digest_keeps_its_events_for_the_next_try(client, app, clock):
    await world(client, app, ("quick_read",))
    gid = await mail_setup(client, app, "quick_read", ["completed"], mode="hourly")
    await app.state.services.settings.set("email.smtp_host", "", "t")        # sending is not possible
    email = app.state.services.email
    email.notify(workflow="quick_read", event="completed", tool_call_id=1, run_id=1, system="TS3", actor="admin")
    await email.idle()
    await email.flush_digests()
    assert (await app.state.services.db.fetchone("SELECT COUNT(*) c FROM email_digest WHERE group_id=?", (gid,)))["c"] == 1 and SENT == []
    await app.state.services.settings.set("email.smtp_host", "smtp.example.com", "t")
    await email.flush_digests()
    assert len(SENT) == 1


async def test_job_starting_workflows_have_a_minimum_interval(client, app):
    await world(client, app, ("heavy_read",))
    assert (await client.post("/api/schedules", json=body("heavy_read", interval_minutes=60))).status_code == 400
    assert (await client.post("/api/schedules", json=body("heavy_read", interval_minutes=1440))).status_code == 200
    for wf in (SapReadinessCheck, SapObsoleteTcodes):
        assert wf.schedulable and wf.schedule_min_minutes == 1440


async def test_old_databases_get_the_new_columns(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("CREATE TABLE workflow_notifications(workflow TEXT NOT NULL, group_id INTEGER NOT NULL, events TEXT NOT NULL, PRIMARY KEY(workflow, group_id));"
                      "CREATE TABLE email_log(id INTEGER PRIMARY KEY, tool_call_id INTEGER NOT NULL, run_id INTEGER NOT NULL, workflow TEXT NOT NULL, event TEXT NOT NULL, "
                      "groups TEXT NOT NULL, recipients INTEGER NOT NULL, status TEXT NOT NULL, error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);")
    con.close()
    db = Database(path)
    await db.connect()

    async def info(table):
        return {r["name"] for r in await db.fetchall(f"PRAGMA table_info({table})")}
    assert "mode" in await info("workflow_notifications") and "key" in await info("email_log")
    await db.close()
