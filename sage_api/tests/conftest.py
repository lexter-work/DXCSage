import pytest_asyncio
from sage.db import Database
from sage.audit import AuditLog
from sage.secretbox import SecretBox
from sage.settings_store import SettingsStore


@pytest_asyncio.fixture
async def db(tmp_path):
    d = Database(tmp_path / "t.db")
    await d.connect()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def audit(db):
    return AuditLog(db)


@pytest_asyncio.fixture
async def box(tmp_path):
    return SecretBox(tmp_path / "keys" / "master.key")


@pytest_asyncio.fixture
async def settings_store(db, box, audit):
    return SettingsStore(db, box, audit)


import httpx
import pytest
from sage.app import create_app
from tests.fakes import FakeRfcClient

BOOT = {"SAGE_BOOTSTRAP_ADMIN_USER": "admin", "SAGE_BOOTSTRAP_ADMIN_PASSWORD": "bootstrap-pass-1"}


@pytest.fixture
def fake_rfc():
    return FakeRfcClient()


@pytest.fixture
def app_kwargs():
    return {}


@pytest_asyncio.fixture
async def app(tmp_path, fake_rfc, app_kwargs, monkeypatch):
    monkeypatch.setenv("SAGE_TEST_MANUAL_DRIVE", "1")
    kw = dict(data_dir=tmp_path / "data", key_dir=tmp_path / "keys", env=BOOT, connector=lambda p: fake_rfc)
    kw.update(app_kwargs)
    a = create_app(**kw)
    async with a.router.lifespan_context(a):
        yield a


@pytest_asyncio.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def login_admin(client):
    r = await client.post("/api/auth/login", json={"username": "admin", "password": "bootstrap-pass-1"})
    assert r.status_code == 200, r.text
    r = await client.post("/api/auth/change-password", json={"old": "bootstrap-pass-1", "new": "admin-pass-12345"})
    assert r.status_code == 200, r.text


from sage.sap.rfc import RfcParams, SapRfc


@pytest_asyncio.fixture
async def rfc(settings_store, fake_rfc):
    async def load(system_id):
        return RfcParams("host", "00", "100", "RFCUSER", "pw")
    return SapRfc(load, lambda p: fake_rfc, settings_store)
