from tests.conftest import login_admin

SYS = {"label": "TS3", "sid": "TS3", "description": "", "ashost": "h", "sysnr": "00", "client": "100",
       "rfc_user": "RFCU", "rfc_password": "pw-secret-1"}
URL = "/api/workflows/sap_readiness_check/systems/1/settings/default_variant/options"


async def setup(client):
    await login_admin(client)
    await client.post("/api/systems", json=SYS)


def varid(fake, rows):
    fake.tables["VARID"], fake.lengths["VARID"] = rows, {"REPORT": 40, "VARIANT": 14}


async def test_lists_variants_of_the_report_sorted_and_unique(client, fake_rfc):
    varid(fake_rfc, [{"REPORT": "RC_COLLECT_ANALYSIS_DATA", "VARIANT": "ZRC_B"}, {"REPORT": "RC_COLLECT_ANALYSIS_DATA", "VARIANT": "ZRC_A"},
                     {"REPORT": "RC_COLLECT_ANALYSIS_DATA", "VARIANT": "ZRC_A"}, {"REPORT": "OTHER_REPORT", "VARIANT": "NOPE"}])
    await setup(client)
    assert (await client.get(URL)).json() == {"options": ["ZRC_A", "ZRC_B"], "error": None}


async def test_sap_error_is_returned_in_the_body(client, fake_rfc):
    await setup(client)                                   # no VARID table: TABLE_NOT_AVAILABLE
    body = (await client.get(URL)).json()
    assert body["options"] == [] and "TABLE_NOT_AVAILABLE" in body["error"]


async def test_only_lookup_settings_and_admins(client, fake_rfc):
    varid(fake_rfc, [])
    await setup(client)
    assert (await client.get(URL.replace("default_variant", "nope"))).status_code == 404
    flags = {s["key"]: s["lookup"] for w in (await client.get("/api/workflows")).json() for s in w["settings"]}
    assert flags == {"default_variant": True}
    await client.post("/api/users", json={"username": "bob", "password": "bob-password-1", "role": "user"})
    await client.post("/api/auth/logout")
    await client.post("/api/auth/login", json={"username": "bob", "password": "bob-password-1"})
    assert (await client.get(URL)).status_code == 403


async def test_unreadable_stored_password_is_a_clear_error_not_a_crash(client, app):
    await setup(client)
    await app.state.services.db.execute("UPDATE systems SET rfc_password_enc='not-a-fernet-token' WHERE id=1")
    app.state.services.rfc.drop(1)
    body = (await client.get(URL)).json()
    assert body["options"] == [] and "cannot be decrypted" in body["error"]
