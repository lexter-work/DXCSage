import pytest
from sage.secretbox import SecretBox


def test_box_roundtrip_and_key_persisted(tmp_path):
    p = tmp_path / "k" / "master.key"
    a = SecretBox(p)
    token = a.encrypt("hunter2")
    assert "hunter2" not in token
    assert SecretBox(p).decrypt(token) == "hunter2"      # same key file reused


async def test_defaults_set_get_and_audit(settings_store, db):
    assert await settings_store.get("agent.max_turns") == 10
    await settings_store.set("agent.max_turns", 5, "admin")
    assert await settings_store.get("agent.max_turns") == 5
    row = await db.fetchone("SELECT detail FROM audit_log WHERE event='config.change'")
    assert '"key": "agent.max_turns"' in row["detail"]


async def test_secret_encrypted_masked_and_not_audited(settings_store, db):
    await settings_store.set("providers.openai_api_key", "sk-live-123", "admin")
    raw = await db.fetchone("SELECT value, is_secret FROM settings WHERE key='providers.openai_api_key'")
    assert raw["is_secret"] == 1 and "sk-live-123" not in raw["value"]
    assert await settings_store.get("providers.openai_api_key") == "sk-live-123"
    pub = await settings_store.public()
    assert pub["providers.openai_api_key"] == {"set": True}
    assert pub["providers.anthropic_api_key"] == {"set": False}
    audit_row = await db.fetchone("SELECT detail FROM audit_log WHERE event='config.change'")
    assert "sk-live-123" not in audit_row["detail"]


async def test_unknown_key_rejected(settings_store):
    with pytest.raises(KeyError):
        await settings_store.set("nope", 1, "admin")


def test_every_setting_has_help_in_the_web_app():
    """sage_web/src/settingsHelp.ts must name exactly the settings the backend defines."""
    import re
    from pathlib import Path
    from sage.settings_store import DEFAULTS
    ts = (Path(__file__).resolve().parents[2] / "sage_web" / "src" / "settingsHelp.ts").read_text(encoding="utf-8")
    documented = set(re.findall(r"^  '([a-z_.]+)': \{", ts, re.M))
    assert documented == set(DEFAULTS), (sorted(set(DEFAULTS) - documented), sorted(documented - set(DEFAULTS)))
