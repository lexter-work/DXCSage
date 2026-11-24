import pytest
from sage.audit import scrub


async def test_chain_verifies_and_scrubs(db, audit):
    await audit.write("auth.login", "alice", detail={"ip": "1.2.3.4", "password": "x", "api_key": "k", "tokens_in": 5})
    await audit.write("run.start", "alice", run_id=None, detail={"n": 1})
    ok, bad = await audit.verify()
    assert ok and bad is None
    row = await db.fetchone("SELECT detail FROM audit_log WHERE id=1")
    assert '"password": "***"' in row["detail"] and '"api_key": "***"' in row["detail"]
    assert '"tokens_in": 5' in row["detail"]


async def test_update_and_delete_blocked(db, audit):
    await audit.write("a", "x")
    with pytest.raises(Exception, match="append-only"):
        await db.execute("UPDATE audit_log SET actor='y' WHERE id=1")
    with pytest.raises(Exception, match="append-only"):
        await db.execute("DELETE FROM audit_log WHERE id=1")


async def test_tamper_detected(db, audit):
    await audit.write("a", "x", detail={"v": 1})
    await audit.write("b", "x", detail={"v": 2})
    await db.execute("DROP TRIGGER audit_no_update")
    await db.execute("UPDATE audit_log SET detail='{\"v\": 99}' WHERE id=1")
    assert await audit.verify() == (False, 1)


def test_scrub_nested():
    assert scrub({"a": [{"passwd": "p"}], "b": 1}) == {"a": [{"passwd": "***"}], "b": 1}
