from sage.sap.rfc import RfcError
from tests.conftest import login_admin

NEW = {"label": "TS3", "sid": "TS3", "description": "test", "ashost": "h", "sysnr": "00", "client": "100",
       "rfc_user": "RFCU", "rfc_password": "s3cret-pw"}


async def test_create_tests_connection_and_activates(client, fake_rfc):
    await login_admin(client)
    r = await client.post("/api/systems", json=NEW)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "active" and body["test"]["ok"] is True
    assert "rfc_password" not in body and "rfc_password_enc" not in body
    assert fake_rfc.count("RFC_PING") == 1


async def test_failed_login_stays_inactive(client, app):
    def boom(p):
        raise RfcError("LOGIN", "bad password")
    app.state.services.rfc._connector = boom
    await login_admin(client)
    body = (await client.post("/api/systems", json=NEW)).json()
    assert body["status"] == "inactive" and body["test"] == {"ok": False, "stage": "login", "message": "bad password"}


async def test_password_encrypted_and_never_audited(client, app):
    await login_admin(client)
    await client.post("/api/systems", json=NEW)
    db = app.state.services.db
    raw = await db.fetchone("SELECT rfc_password_enc FROM systems")
    assert "s3cret-pw" not in raw["rfc_password_enc"]
    assert not await db.fetchone("SELECT 1 FROM audit_log WHERE detail LIKE '%s3cret-pw%'")
    assert (await app.state.services.systems.load_params(1)).passwd == "s3cret-pw"


async def test_validation_and_unique_label(client):
    await login_admin(client)
    assert (await client.post("/api/systems", json={**NEW, "sysnr": "9"})).status_code == 422
    await client.post("/api/systems", json=NEW)
    assert (await client.post("/api/systems", json=NEW)).status_code == 400


async def test_users_see_only_active_label_and_sid(client):
    await login_admin(client)
    await client.post("/api/systems", json=NEW)
    await client.post("/api/users", json={"username": "bob", "password": "bob-password-1", "role": "user"})
    await client.post("/api/auth/logout")
    await client.post("/api/auth/login", json={"username": "bob", "password": "bob-password-1"})
    assert (await client.get("/api/systems")).status_code == 403
    assert (await client.get("/api/systems/active")).json() == [{"id": 1, "label": "TS3", "sid": "TS3"}]


async def test_rotate_credentials_drops_cached_connection(client, app, fake_rfc):
    await login_admin(client)
    await client.post("/api/systems", json=NEW)
    await app.state.services.rfc.ping(1)
    r = await client.put("/api/systems/1/credentials", json={"user": "NEW", "password": "another-pw-1"})
    assert r.status_code == 200 and 1 not in app.state.services.rfc._clients
    assert (await app.state.services.systems.load_params(1)).user == "NEW"
