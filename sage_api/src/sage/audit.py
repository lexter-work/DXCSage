"""Append-only, hash-chained audit log. All code writes through AuditLog.write."""
import hashlib
import json

from sage.util import iso

_SENSITIVE = ("password", "passwd", "secret", "api_key", "auth_token", "access_token", "session_token")
_ZERO = "0" * 64


def scrub(v):
    if isinstance(v, dict):
        return {k: ("***" if any(s in k.lower() for s in _SENSITIVE) else scrub(x)) for k, x in v.items()}
    if isinstance(v, list):
        return [scrub(x) for x in v]
    return v


def _hash(prev, ts, event, actor, run_id, detail):
    payload = json.dumps([ts, event, actor, run_id, detail], separators=(",", ":"))
    return hashlib.sha256((prev + "|" + payload).encode()).hexdigest()


class AuditLog:
    def __init__(self, db):
        self._db = db

    async def write(self, event, actor, run_id=None, detail=None) -> int:
        detail_s = json.dumps(scrub(detail or {}), sort_keys=True, default=str)
        ts = iso()
        async with self._db.tx() as t:
            last = await t.fetchone("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1")
            prev = last["hash"] if last else _ZERO
            h = _hash(prev, ts, event, actor, run_id, detail_s)
            return await t.execute(
                "INSERT INTO audit_log(ts,event,actor,run_id,detail,prev_hash,hash) VALUES(?,?,?,?,?,?,?)",
                (ts, event, actor, run_id, detail_s, prev, h))

    async def verify(self) -> tuple[bool, int | None]:
        prev = _ZERO
        for r in await self._db.fetchall("SELECT * FROM audit_log ORDER BY id"):
            if r["prev_hash"] != prev or r["hash"] != _hash(prev, r["ts"], r["event"], r["actor"], r["run_id"], r["detail"]):
                return False, r["id"]
            prev = r["hash"]
        return True, None
