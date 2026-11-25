"""Builds every service once, at app start. Later tasks add lines here."""
import os
from pathlib import Path
from types import SimpleNamespace

from sage.audit import AuditLog
from sage.auth import AuthService
from sage.db import Database
from sage.health import HealthService
from sage.providers.registry import default_providers
from sage.sap.rfc import SapRfc, pyrfc_connector
from sage.runtime.agent import AgentService
from sage.secretbox import SecretBox
from sage.systems import SystemsService
from sage.settings_store import SettingsStore
from sage.usage import UsageService
from sage.util import utcnow
from sage.workflow_setup import WorkflowSetupService
from sage.workflows.registry import discover


async def build_services(*, data_dir, key_dir, connector=None, providers=None, workflows=None, clock=None):
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
    systems = SystemsService(db, box, audit, rfc)
    holder.systems = systems
    wf = workflows if workflows is not None else discover()
    health = HealthService(db, audit, rfc, systems, settings, wf, clock)
    setup = WorkflowSetupService(db, audit, systems, health, wf, settings, clock)
    usage = UsageService(db, clock)
    agent = AgentService(db=db, audit=audit, settings=settings, providers=providers or default_providers(), workflows=wf,
                         setup=setup, rfc=rfc, data_dir=data_dir, usage=usage, clock=clock)
    return SimpleNamespace(usage=usage, agent=agent, manual_drive=os.getenv("SAGE_TEST_MANUAL_DRIVE") == "1", db=db, box=box, audit=audit, settings=settings, auth=auth, rfc=rfc, systems=systems,
                           data_dir=data_dir, clock=clock, connector=connector,
                           providers=providers, workflows=wf, health=health, setup=setup)
