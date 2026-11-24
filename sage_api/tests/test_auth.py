from tests.conftest import login_admin


async def test_bootstrap_admin_forces_password_change(client):
    r = await client.post("/api/auth/login", json={"username": "admin", "password": "bootstrap-pass-1"})
    assert r.status_code == 200
    assert (await client.get("/api/auth/me")).json()["must_change_password"] is True
    assert (await client.get("/api/users")).status_code == 403          # blocked until changed
    await client.post("/api/auth/change-password", json={"old": "bootstrap-pass-1", "new": "admin-pass-12345"})
    assert (await client.get("/api/users")).status_code == 200


async def test_bootstrap_ignored_when_admin_exists(app):
    assert await app.state.services.auth.ensure_bootstrap_admin(
        {"SAGE_BOOTSTRAP_ADMIN_USER": "other", "SAGE_BOOTSTRAP_ADMIN_PASSWORD": "another-pass-1"}) is False
    assert len(await app.state.services.auth.list_users()) == 1


async def test_login_fail_rate_limit_and_audit(client, app):
    for _ in range(5):
        r = await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert r.status_code == 401
    r = await client.post("/api/auth/login", json={"username": "admin", "password": "bootstrap-pass-1"})
    assert r.status_code == 429
    n = await app.state.services.db.fetchone("SELECT COUNT(*) c FROM audit_log WHERE event='auth.fail'")
    assert n["c"] >= 5


async def test_user_admin_flow_and_disable(client):
    await login_admin(client)
    r = await client.post("/api/users", json={"username": "bob", "password": "bob-password-1", "role": "user"})
    assert r.status_code == 200
    uid = r.json()["id"]
    assert (await client.patch(f"/api/users/{uid}", json={"disabled": True})).status_code == 200
    await client.post("/api/auth/logout")
    r = await client.post("/api/auth/login", json={"username": "bob", "password": "bob-password-1"})
    assert r.status_code == 401                                          # disabled, never deleted


async def test_non_admin_forbidden(client):
    await login_admin(client)
    await client.post("/api/users", json={"username": "bob", "password": "bob-password-1", "role": "user"})
    await client.post("/api/auth/logout")
    await client.post("/api/auth/login", json={"username": "bob", "password": "bob-password-1"})
    assert (await client.get("/api/users")).status_code == 403
    assert (await client.get("/api/auth/me")).json()["role"] == "user"
