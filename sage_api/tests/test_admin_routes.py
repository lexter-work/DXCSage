from tests.conftest import login_admin


async def test_settings_get_put_masks_secrets(client):
    await login_admin(client)
    assert (await client.put("/api/settings", json={"key": "providers.openai_api_key", "value": "sk-1"})).status_code == 200
    s = (await client.get("/api/settings")).json()
    assert s["providers.openai_api_key"] == {"set": True} and s["agent.max_turns"] == 10
    assert (await client.put("/api/settings", json={"key": "nope", "value": 1})).status_code == 400


async def test_audit_list_export_verify(client):
    await login_admin(client)
    rows = (await client.get("/api/audit?event=auth.login")).json()
    assert rows and all(r["event"] == "auth.login" for r in rows)
    csv = (await client.get("/api/audit/export.csv")).text
    assert csv.splitlines()[0].startswith("id,ts,event,actor") and "auth.login" in csv
    assert (await client.post("/api/audit/verify")).json() == {"ok": True, "bad_id": None}


async def test_runs_detail_includes_deleted_chats_and_requires_admin(client, app):
    await login_admin(client)
    db = app.state.services.db
    await db.execute("INSERT INTO chats(id,user_id,title,provider,model,created_at,deleted_at) VALUES(5,1,'c','p','m','t','t')")
    await db.execute("INSERT INTO runs(id,chat_id,user_id,provider,model,status,started_at) VALUES(7,5,1,'p','m','done','t')")
    runs = (await client.get("/api/runs")).json()
    assert runs[0]["id"] == 7 and runs[0]["chat_deleted"] is True
    d = (await client.get("/api/runs/7/detail")).json()
    assert d["run"]["id"] == 7 and d["tool_calls"] == []
    await client.post("/api/users", json={"username": "bob", "password": "bob-password-1", "role": "user"})
    await client.post("/api/auth/logout")
    await client.post("/api/auth/login", json={"username": "bob", "password": "bob-password-1"})
    for path in ("/api/runs", "/api/audit", "/api/usage", "/api/settings"):
        assert (await client.get(path)).status_code == 403
