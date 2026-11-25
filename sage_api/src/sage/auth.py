"""Local accounts, sessions, bootstrap admin. Users are disabled, never deleted."""
import hashlib
import secrets
from datetime import timedelta

from sage.passwords import hash_password, verify_password
from sage.util import iso, parse_iso, utcnow

SESSION_TTL = timedelta(days=7)
FAIL_WINDOW = timedelta(minutes=15)
MAX_FAILS = 5
MIN_PASSWORD = 10


class AuthError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _th(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    def __init__(self, db, audit, clock=utcnow):
        self._db, self._audit, self._clock = db, audit, clock
        self._fails: dict[tuple[str, str], list] = {}

    async def create_user(self, username, password, role, actor, must_change=False) -> int:
        if role not in ("admin", "user"):
            raise AuthError("bad_role")
        if len(password) < MIN_PASSWORD:
            raise AuthError("password_too_short")
        if await self._db.fetchone("SELECT id FROM users WHERE username=?", (username,)):
            raise AuthError("username_taken")
        uid = await self._db.execute(
            "INSERT INTO users(username,password_hash,role,must_change_password,created_at) VALUES(?,?,?,?,?)",
            (username, hash_password(password), role, int(must_change), iso(self._clock())))
        await self._audit.write("admin.user_create", actor, detail={"username": username, "role": role})
        return uid

    async def login(self, username, password, ip) -> str:
        now = self._clock()
        key = (username.lower(), ip)
        recent = [t for t in self._fails.get(key, []) if now - t < FAIL_WINDOW]
        self._fails[key] = recent
        if len(recent) >= MAX_FAILS:
            await self._audit.write("auth.fail", username, detail={"ip": ip, "reason": "rate_limited"})
            raise AuthError("rate_limited")
        user = await self._db.fetchone("SELECT * FROM users WHERE username=?", (username,))
        if not (user and not user["disabled"] and verify_password(user["password_hash"], password)):
            recent.append(now)
            await self._audit.write("auth.fail", username, detail={"ip": ip, "reason": "invalid_credentials"})
            raise AuthError("invalid_credentials")
        token = secrets.token_urlsafe(32)
        await self._db.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)",
                               (_th(token), user["id"], iso(now + SESSION_TTL)))
        await self._audit.write("auth.login", username, detail={"ip": ip})
        return token

    async def user_for_token(self, token):
        row = await self._db.fetchone(
            "SELECT u.*, s.expires_at FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?", (_th(token),))
        if not row or row["disabled"] or parse_iso(row["expires_at"]) < self._clock():
            return None
        row.pop("password_hash", None)
        row["must_change_password"] = bool(row["must_change_password"])
        return row

    async def logout(self, token):
        await self._db.execute("DELETE FROM sessions WHERE token_hash=?", (_th(token),))

    async def change_password(self, user_id, old, new, actor):
        user = await self._db.fetchone("SELECT * FROM users WHERE id=?", (user_id,))
        if not verify_password(user["password_hash"], old):
            raise AuthError("invalid_credentials")
        if len(new) < MIN_PASSWORD:
            raise AuthError("password_too_short")
        await self._db.execute("UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?",
                               (hash_password(new), user_id))
        await self._audit.write("auth.password_change", actor)

    async def reset_password(self, user_id, new, actor):
        if len(new) < MIN_PASSWORD:
            raise AuthError("password_too_short")
        await self._db.execute("UPDATE users SET password_hash=?, must_change_password=1 WHERE id=?",
                               (hash_password(new), user_id))
        await self._db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        await self._audit.write("admin.user_reset_password", actor, detail={"user_id": user_id})

    async def set_disabled(self, user_id, disabled, actor):
        await self._db.execute("UPDATE users SET disabled=? WHERE id=?", (int(disabled), user_id))
        if disabled:
            await self._db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        await self._audit.write("admin.user_disable" if disabled else "admin.user_enable", actor, detail={"user_id": user_id})

    async def set_role(self, user_id, role, actor):
        if role not in ("admin", "user"):
            raise AuthError("bad_role")
        await self._db.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
        await self._audit.write("admin.user_role", actor, detail={"user_id": user_id, "role": role})

    async def list_users(self):
        return await self._db.fetchall(
            "SELECT id,username,role,disabled,must_change_password,created_at FROM users ORDER BY id")

    async def ensure_bootstrap_admin(self, env) -> bool:
        if await self._db.fetchone("SELECT id FROM users WHERE role='admin'"):
            return False
        user, pw = env.get("SAGE_BOOTSTRAP_ADMIN_USER"), env.get("SAGE_BOOTSTRAP_ADMIN_PASSWORD")
        if not user or not pw:
            return False
        await self.create_user(user, pw, "admin", "bootstrap", must_change=False)
        await self._audit.write("auth.bootstrap", "bootstrap", detail={"username": user})
        return True
