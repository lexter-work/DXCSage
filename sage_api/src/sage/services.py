"""Builds every service once, at app start. Later tasks add lines here."""
import os
from pathlib import Path
from types import SimpleNamespace

from sage.audit import AuditLog
from sage.auth import AuthService
from sage.db import Database
from sage.emailer import EmailService, smtp_send
from sage.health import HealthService
from sage.providers.registry import default_providers
from sage.sap.rfc import SapRfc, pyrfc_connector
from sage.sap.ssh import SapSsh, asyncssh_connector, asyncssh_host_key
from sage.runtime.agent import AgentService
from sage.secretbox import SecretBox
from sage.systems import SystemsService
from sage.policies import PolicyService
from sage.schedules import ScheduleService
from sage.settings_store import SettingsStore
from sage.uploads import UploadService
from sage.usage import UsageService
from sage.util import utcnow
from sage.workflow_setup import WorkflowSetupService
from sage.workflows.registry import discover


async def build_services(*, data_dir, key_dir, connector=None, providers=None, workflows=None, clock=None, ssh_connector=None, ssh_host_key=None, mail_sender=None):
    clock = clock or utcnow
    data_dir, key_dir = Path(data_dir), Path(key_dir)
    db = Database(data_dir / "sage.db")
    await db.connect()
    box = SecretBox(key_dir / "master.key")
    audit = AuditLog(db)
    settings = SettingsStore(db, box, audit)
    auth = AuthService(db, audit, clock)
    holder = SimpleNamespace(systems=None)

    async def load_params(system_id):
        return await holder.systems.load_params(system_id)

    async def load_names(system_id):
        return await holder.systems.abap_names(system_id)

    rfc = SapRfc(load_params, connector or pyrfc_connector, settings, load_names)
    ssh = SapSsh(lambda system_id: holder.systems.load_ssh(system_id), ssh_connector or asyncssh_connector, ssh_host_key or asyncssh_host_key)
    systems = SystemsService(db, box, audit, rfc)
    holder.systems = systems
    wf = workflows if workflows is not None else discover()
    health = HealthService(db, audit, rfc, systems, settings, wf, clock, ssh)
    setup = WorkflowSetupService(db, audit, systems, health, wf, settings, clock)
    usage = UsageService(db, clock)
    email = EmailService(db, settings, audit, wf, clock, mail_sender or smtp_send)
    schedules = ScheduleService(db, audit, wf, systems, clock)
    uploads = UploadService(db, audit, data_dir, clock)
    policies = PolicyService(db, audit, clock)
    agent = AgentService(db=db, audit=audit, settings=settings, providers=providers or default_providers(), workflows=wf,
                         setup=setup, rfc=rfc, data_dir=data_dir, usage=usage, ssh=ssh, email=email, schedules=schedules, uploads=uploads, policies=policies, clock=clock)
    return SimpleNamespace(usage=usage, agent=agent, manual_drive=os.getenv("SAGE_TEST_MANUAL_DRIVE") == "1", db=db, box=box, audit=audit, settings=settings, auth=auth, rfc=rfc, ssh=ssh, email=email, schedules=schedules, uploads=uploads, policies=policies, systems=systems,
                           data_dir=data_dir, clock=clock, connector=connector,
                           providers=providers, workflows=wf, health=health, setup=setup)
