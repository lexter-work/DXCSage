# DXC Sage Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline, one pass). Workspace pace rules in `D:\User\Documents\Programming\AGENTS.md` override skill ceremony: no baseline run, no worktree, no branch, no subagent review, no full-suite run. Each task runs only its own tests, once. One commit at the very end of the plan.

**Goal:** Build `sage_api`, the FastAPI backend of DXC Sage: auth, chats, agent loop with Claude and GPT, durable workflows, SAP systems registry, per-system workflow setup with guides, health checks, audit and usage counts.

**Architecture:** One async FastAPI process with one SQLite file (WAL). Tools are workflows composed of shared tasks; every task call is a stored step, so a long run can be replayed after a restart. SAP access is PyRFC only (`RFC_READ_TABLE` for reads, named `ZFM_*` for the rest). All settings and secrets live in the DB; `.env` holds only the bootstrap admin.

**Tech Stack:** Python 3.12, FastAPI, aiosqlite, pydantic v2, cryptography (Fernet), argon2-cffi, anthropic, openai, pyrfc (optional extra), pytest + pytest-asyncio, uv.

**Spec:** `Applications/DXCSage/docs/superpowers/specs/2026-11-24-dxc-sage-design.md`. Frontend plan: `2026-11-24-dxc-sage-frontend.md` (same folder), written to the API in this plan.

## Global Constraints

- Project root `Applications/DXCSage/`; backend in `sage_api/`, package `sage` in `sage_api/src/sage/`. Ports: `sage_api` 29700, `sage_web` 29701 (checked free in the workspace).
- Use `uv` (never pip). Run tests from `Applications/DXCSage/sage_api` with `uv run pytest <file> -q`.
- All I/O async. Blocking pyrfc calls run in `asyncio.to_thread`. Inside `async with db.tx()` use only the `t` object, never `db.*` (the lock is not re-entrant).
- No `.env` settings and no JSON configs. Only `SAGE_BOOTSTRAP_ADMIN_USER` and `SAGE_BOOTSTRAP_ADMIN_PASSWORD` come from the environment. `SAGE_DATA_DIR` and `SAGE_KEY_DIR` are set by `docker-compose.yml` (defaults `.data`, `.keys` for local runs).
- Secrets never returned by any API and never written to audit (`scrub`).
- Never call a write or job-scheduling function module from a health check.
- Users and systems are never deleted (disabled only). Chats are soft-deleted. `audit_log` is append-only.
- Tool names given to providers match `^[a-zA-Z0-9_-]{1,64}$` (workflow names use underscores).
- Not verifiable here and labelled so in code comments and docs: pyrfc against a real SAP system, the Anthropic and OpenAI network paths, `SUSR_USER_AUTH_FOR_OBJ_GET`, `CWBNTCUST/PRSTATUS`, the `IT_NOTES` row shape of `ZFM_RC_NOTES_DOWNLOAD`.

## File Structure

```
Applications/DXCSage/
  AGENTS.md  CLAUDE.md  README.md  .env.example  .gitignore  docker-compose.yml
  sage_api/
    pyproject.toml  Dockerfile
    src/sage/
      app.py services.py util.py schema.py db.py audit.py secretbox.py settings_store.py
      passwords.py auth.py deps.py systems.py health.py guide.py workflow_setup.py usage.py
      sap/{rfc.py,requirements.py}
      tasks/{base.py,sap_read_table.py,sap_job_status.py,rc_notes_download.py,rc_start_analysis.py,rc_fetch_archive.py}
      workflows/{base.py,registry.py,sap_readiness_check.py}
      runtime/{errors.py,context.py,agent.py}
      providers/{base.py,anthropic_provider.py,openai_provider.py,registry.py}
      routes/{auth_routes.py,users.py,systems_routes.py,workflow_routes.py,chat_routes.py,admin_routes.py}
      static/rfc/*.txt        (ABAP specs copied from the reference zip)
    tests/{conftest.py,fakes.py,test_*.py}
```

---

### Task 0: Project scaffold

**Files:**
- Create: `Applications/DXCSage/{.gitignore,.env.example,AGENTS.md,CLAUDE.md}`, `sage_api/pyproject.toml`, `sage_api/src/sage/{__init__.py,app.py,util.py}`, `sage_api/tests/{__init__.py,test_health.py}`

**Interfaces:**
- Produces: `create_app(*, data_dir=None, key_dir=None, connector=None, providers=None, workflows=None, env=None, clock=None) -> FastAPI`; `sage.util.utcnow() -> datetime`, `iso(dt=None) -> str`, `parse_iso(s) -> datetime`.

- [ ] **Step 1: Confirm ports and init the repo**

Run (PowerShell):
```powershell
cd D:\User\Documents\Programming\Applications\DXCSage
git init
```
Expected: `Initialized empty Git repository`. (Ports 29700 and 29701 were checked free in the workspace.)

- [ ] **Step 2: Write project files**

`.gitignore`:
```
.venv/
__pycache__/
.pytest_cache/
.data/
.keys/
.env
node_modules/
dist/
sage_api/vendor/nwrfcsdk/*
!sage_api/vendor/nwrfcsdk/.gitkeep
_references/
```

`.env.example`:
```
# Copy to .env (git-ignored). Used only while no admin account exists.
SAGE_BOOTSTRAP_ADMIN_USER=admin
SAGE_BOOTSTRAP_ADMIN_PASSWORD=
```

`AGENTS.md`:
```markdown
# DXC Sage

Small agentic harness (Claude and GPT only) with SAP workflow tools. Two services: `sage_api` (FastAPI, port 29700) and `sage_web` (Vue 3, port 29701). Spec: `docs/superpowers/specs/2026-11-24-dxc-sage-design.md`.

## Agent instructions
This file is the one instruction file for every coding agent; `CLAUDE.md` only imports it. Edit this file, never `CLAUDE.md`.

## Commands
- Backend tests: `cd sage_api; uv run pytest tests/<file> -q`
- Frontend: `cd sage_web; pnpm install; pnpm dev`

## Rules
- No `.env` settings and no JSON configs: settings and secrets live in the DB. `.env` has only the bootstrap admin.
- SAP access is PyRFC only (no hdbsql, no SSH). Reads go through `RFC_READ_TABLE`.
- The model sees workflows only. Workflows are built from shared tasks in `tasks/`; never copy a task into a workflow.
- Every task call goes through `ctx.task` / `ctx.wait` so it is a stored, replayable, audited step.
- Health checks never call write or job-scheduling function modules.
- Users and systems are disabled, never deleted. Chats are soft-deleted. `audit_log` is append-only.
- UI uses relative URLs only; `GET /health` answers without auth.
```

`CLAUDE.md`: `@AGENTS.md`

`sage_api/pyproject.toml`:
```toml
[project]
name = "sage-api"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115", "uvicorn[standard]>=0.30", "aiosqlite>=0.20", "pydantic>=2.7",
  "cryptography>=43", "argon2-cffi>=23.1", "anthropic>=0.40", "openai>=1.50", "httpx>=0.27",
]

[project.optional-dependencies]
rfc = ["pyrfc>=3.3"]

[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.24"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/sage"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["src"]
testpaths = ["tests"]
```

`sage_api/src/sage/util.py`:
```python
"""Time helpers. One place, so tests can pass their own clock."""
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or utcnow()).isoformat(timespec="seconds")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)
```

`sage_api/src/sage/app.py` (extended by later tasks):
```python
"""FastAPI app factory. Services are built in lifespan (see services.py)."""
from fastapi import FastAPI


def create_app(*, data_dir=None, key_dir=None, connector=None, providers=None,
               workflows=None, env=None, clock=None) -> FastAPI:
    app = FastAPI(title="DXC Sage")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app
```

`sage_api/tests/test_health.py`:
```python
import httpx
from sage.app import create_app


async def test_health_open():
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
```

- [ ] **Step 3: Install and run**

Run: `cd sage_api; uv sync; uv run pytest tests/test_health.py -q`
Expected: `1 passed`.

---

### Task 1: Database schema and audit chain

**Files:**
- Create: `sage_api/src/sage/{schema.py,db.py,audit.py}`, `sage_api/tests/{conftest.py,test_audit.py}`

**Interfaces:**
- Produces: `Database(path)` with `connect()`, `close()`, `execute(sql, params=()) -> int` (lastrowid), `fetchone(sql, params=()) -> dict | None`, `fetchall(sql, params=()) -> list[dict]`, `tx()` async context manager yielding `t` with the same three query methods.
- Produces: `AuditLog(db)` with `write(event, actor, run_id=None, detail=None) -> int`, `verify() -> tuple[bool, int | None]`; `scrub(obj)`.

- [ ] **Step 1: Write the failing tests**

`tests/conftest.py`:
```python
import pytest_asyncio
from sage.db import Database
from sage.audit import AuditLog


@pytest_asyncio.fixture
async def db(tmp_path):
    d = Database(tmp_path / "t.db")
    await d.connect()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def audit(db):
    return AuditLog(db)
```

`tests/test_audit.py`:
```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_audit.py -q` — Expected: FAIL `ModuleNotFoundError: sage.db`.

- [ ] **Step 3: Implement**

`src/sage/schema.py`:
```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin','user')), disabled INTEGER NOT NULL DEFAULT 0,
  must_change_password INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chats(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), title TEXT NOT NULL,
  provider TEXT NOT NULL, model TEXT NOT NULL, created_at TEXT NOT NULL, deleted_at TEXT);
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL REFERENCES chats(id), user_id INTEGER NOT NULL REFERENCES users(id),
  provider TEXT NOT NULL, model TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('running','waiting','done','failed','cancelled')),
  resume_at TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
  tokens_in INTEGER NOT NULL DEFAULT 0, tokens_out INTEGER NOT NULL DEFAULT 0,
  error TEXT, started_at TEXT NOT NULL, ended_at TEXT);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL REFERENCES chats(id), run_id INTEGER REFERENCES runs(id),
  role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS run_events(
  id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES runs(id), type TEXT NOT NULL,
  data TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tool_calls(
  id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES runs(id), provider_call_id TEXT NOT NULL,
  workflow TEXT NOT NULL, system_id INTEGER, input TEXT NOT NULL, output TEXT,
  status TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT);
CREATE TABLE IF NOT EXISTS tool_steps(
  id INTEGER PRIMARY KEY, tool_call_id INTEGER NOT NULL REFERENCES tool_calls(id),
  seq INTEGER NOT NULL, kind TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
  name TEXT NOT NULL, workflow TEXT NOT NULL, input TEXT NOT NULL, output TEXT,
  status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL,
  UNIQUE(tool_call_id, seq, kind, attempt));
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, event TEXT NOT NULL, actor TEXT NOT NULL,
  run_id INTEGER, detail TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
  BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
  BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TABLE IF NOT EXISTS usage_counters(
  user_id INTEGER NOT NULL REFERENCES users(id), day TEXT NOT NULL,
  requests INTEGER NOT NULL DEFAULT 0, tokens_in INTEGER NOT NULL DEFAULT 0, tokens_out INTEGER NOT NULL DEFAULT 0,
  workflow_calls INTEGER NOT NULL DEFAULT 0, task_calls INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(user_id, day));
CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY, value TEXT NOT NULL, is_secret INTEGER NOT NULL DEFAULT 0,
  updated_by TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS systems(
  id INTEGER PRIMARY KEY, label TEXT UNIQUE NOT NULL, sid TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
  ashost TEXT NOT NULL, sysnr TEXT NOT NULL, client TEXT NOT NULL, rfc_user TEXT NOT NULL,
  rfc_password_enc TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('inactive','active','disabled')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS system_health(
  id INTEGER PRIMARY KEY, system_id INTEGER NOT NULL REFERENCES systems(id), workflow TEXT NOT NULL,
  req_kind TEXT NOT NULL, req_key TEXT NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL,
  checked_at TEXT NOT NULL, UNIQUE(system_id, workflow, req_kind, req_key));
CREATE TABLE IF NOT EXISTS workflow_systems(
  id INTEGER PRIMARY KEY, workflow TEXT NOT NULL, system_id INTEGER NOT NULL REFERENCES systems(id),
  status TEXT NOT NULL CHECK(status IN ('setup','enabled','disabled')),
  settings TEXT NOT NULL DEFAULT '{}', enabled_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(workflow, system_id));
"""
```

`src/sage/db.py`:
```python
"""One aiosqlite connection behind a lock. Use db.tx() for multi-statement writes."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from sage.schema import SCHEMA


class _Ops:
    def __init__(self, conn):
        self._c = conn

    async def execute(self, sql, params=()):
        cur = await self._c.execute(sql, params)
        return cur.lastrowid

    async def fetchone(self, sql, params=()):
        cur = await self._c.execute(sql, params)
        row = await cur.fetchone()
        return dict(row) if row else None

    async def fetchall(self, sql, params=()):
        cur = await self._c.execute(sql, params)
        return [dict(r) for r in await cur.fetchall()]


class Database(_Ops):
    def __init__(self, path):
        super().__init__(None)
        self._path = Path(path)
        self._lock = asyncio.Lock()

    async def connect(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._c = await aiosqlite.connect(self._path)
        self._c.row_factory = aiosqlite.Row
        await self._c.execute("PRAGMA journal_mode=WAL")
        await self._c.execute("PRAGMA foreign_keys=ON")
        await self._c.executescript(SCHEMA)
        await self._c.commit()

    async def close(self):
        await self._c.close()

    async def execute(self, sql, params=()):
        async with self.tx() as t:
            return await t.execute(sql, params)

    async def fetchone(self, sql, params=()):
        async with self._lock:
            return await super().fetchone(sql, params)

    async def fetchall(self, sql, params=()):
        async with self._lock:
            return await super().fetchall(sql, params)

    @asynccontextmanager
    async def tx(self):
        async with self._lock:
            try:
                yield _Ops(self._c)
                await self._c.commit()
            except BaseException:
                await self._c.rollback()
                raise
```

`src/sage/audit.py`:
```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_audit.py -q` — Expected: `4 passed`.

---

### Task 2: Secret box and settings store

**Files:**
- Create: `sage_api/src/sage/{secretbox.py,settings_store.py}`, `sage_api/tests/test_settings.py`
- Modify: `sage_api/tests/conftest.py` (add fixtures)

**Interfaces:**
- Produces: `SecretBox(key_path)` with `encrypt(str) -> str`, `decrypt(str) -> str`. `SettingsStore(db, box, audit)` with `get(key)`, `set(key, value, actor)`, `public() -> dict`; `DEFAULTS`, `SECRET_KEYS`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/conftest.py`:
```python
from sage.secretbox import SecretBox
from sage.settings_store import SettingsStore


@pytest_asyncio.fixture
async def box(tmp_path):
    return SecretBox(tmp_path / "keys" / "master.key")


@pytest_asyncio.fixture
async def settings_store(db, box, audit):
    return SettingsStore(db, box, audit)
```

`tests/test_settings.py`:
```python
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
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_settings.py -q` — FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/sage/secretbox.py`:
```python
"""Fernet encryption. The key file lives in its own Docker volume, apart from the SQLite file."""
import os
from pathlib import Path

from cryptography.fernet import Fernet


class SecretBox:
    def __init__(self, key_path):
        p = Path(key_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_bytes(Fernet.generate_key())
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass
        self._f = Fernet(p.read_bytes())

    def encrypt(self, plain: str) -> str:
        return self._f.encrypt(plain.encode()).decode()

    def decrypt(self, token: str) -> str:
        return self._f.decrypt(token.encode()).decode()
```

`src/sage/settings_store.py`:
```python
"""All configuration lives here. Defaults are seeded in code; admins change them in the UI."""
import json

from sage.util import iso

SECRET_KEYS = {"providers.anthropic_api_key", "providers.openai_api_key"}

DEFAULTS: dict = {
    "agent.max_turns": 10,
    "providers.max_tokens": 4096,
    "providers.models": {
        "anthropic": ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"],
        "openai": ["gpt-5"],
    },
    "providers.anthropic_api_key": "",
    "providers.openai_api_key": "",
    "wait.backoff": [[60, 10], [300, 60], [3600, 300], [10800, 900], [86400, 3600]],
    "wait.max_wait": 86400,
    "health.max_age": 86400,
    "sap.rowcount_cap": 5000,
    "workflows.disabled": [],
    "readiness.prerequisite_notes": {
        "download_wait_seconds": 600,
        "download_poll_seconds": 15,
        "require_implemented": True,
        "implementation_status": {"table": "CWBNTCUST", "field": "PRSTATUS", "implemented_values": ["E"]},
        "notes": [
            {"number": "1668882", "remark": "Latest version required."},
            {"number": "2971435", "remark": "Latest version required."},
            {"number": "2758146", "remark": "If SAP Note 2310438 was implemented previously, revert it first."},
            {"number": "2399707", "remark": "Minimum requirement for SAP Readiness Check."},
            {"number": "2903677"},
            {"number": "2502552"},
            {"number": "2827612", "conditional": True,
             "remark": "Only if ST-PI <= 2008_1_700 SP27, 2008_1_710 SP27 or 740 SP17."},
            {"number": "2781766"},
        ],
    },
}


class SettingsStore:
    def __init__(self, db, box, audit):
        self._db, self._box, self._audit = db, box, audit

    async def get(self, key):
        if key not in DEFAULTS:
            raise KeyError(key)
        row = await self._db.fetchone("SELECT value,is_secret FROM settings WHERE key=?", (key,))
        if not row:
            return DEFAULTS[key]
        return self._box.decrypt(row["value"]) if row["is_secret"] else json.loads(row["value"])

    async def set(self, key, value, actor):
        if key not in DEFAULTS:
            raise KeyError(key)
        secret = key in SECRET_KEYS
        stored = self._box.encrypt(str(value)) if secret else json.dumps(value)
        await self._db.execute(
            "INSERT INTO settings(key,value,is_secret,updated_by,updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, is_secret=excluded.is_secret, "
            "updated_by=excluded.updated_by, updated_at=excluded.updated_at",
            (key, stored, int(secret), actor, iso()))
        await self._audit.write("config.change", actor, detail={"key": key} if secret else {"key": key, "value": value})

    async def public(self) -> dict:
        out = {}
        for key in DEFAULTS:
            v = await self.get(key)
            out[key] = {"set": bool(v)} if key in SECRET_KEYS else v
        return out
```

- [ ] **Step 4: Run to verify it passes** — `uv run pytest tests/test_settings.py -q` — Expected: `4 passed`.

---

### Task 3: Auth, users, bootstrap admin, app wiring

**Files:**
- Create: `sage_api/src/sage/{passwords.py,auth.py,deps.py,services.py}`, `sage_api/src/sage/routes/{__init__.py,auth_routes.py,users.py}`, `sage_api/tests/{fakes.py,test_auth.py}`
- Modify: `sage_api/src/sage/app.py`, `sage_api/tests/conftest.py`

**Interfaces:**
- Produces: `AuthService(db, audit, clock=utcnow)` with `create_user(username, password, role, actor, must_change=False) -> int`, `login(username, password, ip) -> str`, `user_for_token(token) -> dict | None`, `logout(token)`, `change_password(user_id, old, new, actor)`, `reset_password(user_id, new, actor)`, `set_disabled(user_id, disabled, actor)`, `set_role(user_id, role, actor)`, `list_users() -> list[dict]`, `ensure_bootstrap_admin(env) -> bool`; `AuthError(code)`.
- Produces: `build_services(*, data_dir, key_dir, connector, providers, workflows, clock) -> SimpleNamespace` (attributes added task by task), FastAPI deps `current_user`, `admin_user`. Test fixtures `app`, `client`, `app_kwargs`, `login_admin(client)`, `FakeRfcClient` (Task 4 fills `fakes.py`; create the file with the class stub now).
- Routes: `POST /api/auth/login {username,password}`, `POST /api/auth/logout`, `GET /api/auth/me`, `POST /api/auth/change-password {old,new}`; admin: `GET /api/users`, `POST /api/users {username,password,role}`, `PATCH /api/users/{id} {role?,disabled?}`, `POST /api/users/{id}/reset-password {password}`.

- [ ] **Step 1: Write the failing tests**

`tests/fakes.py` (stub now, extended in Task 4):
```python
class FakeRfcClient:
    def __init__(self, tables=None, lengths=None, functions=None):
        self.tables, self.lengths, self.functions, self.calls = tables or {}, lengths or {}, functions or {}, []

    def close(self):
        pass
```

Append to `tests/conftest.py`:
```python
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
async def app(tmp_path, fake_rfc, app_kwargs):
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
```

`tests/test_auth.py`:
```python
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
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_auth.py -q` — FAIL (no `/api/auth/login`).

- [ ] **Step 3: Implement**

`src/sage/passwords.py`:
```python
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_ph = PasswordHasher()


def hash_password(p: str) -> str:
    return _ph.hash(p)


def verify_password(h: str, p: str) -> bool:
    try:
        return _ph.verify(h, p)
    except (VerifyMismatchError, InvalidHashError):
        return False
```

`src/sage/auth.py`:
```python
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
        await self.create_user(user, pw, "admin", "bootstrap", must_change=True)
        await self._audit.write("auth.bootstrap", "bootstrap", detail={"username": user})
        return True
```

`src/sage/deps.py`:
```python
from fastapi import Depends, HTTPException, Request

_ALLOWED_WHEN_CHANGE_PENDING = ("/api/auth/me", "/api/auth/change-password", "/api/auth/logout")


async def current_user(request: Request) -> dict:
    token = request.cookies.get("sage_session")
    user = await request.app.state.services.auth.user_for_token(token) if token else None
    if not user:
        raise HTTPException(401, "not_authenticated")
    if user["must_change_password"] and request.url.path not in _ALLOWED_WHEN_CHANGE_PENDING:
        raise HTTPException(403, "password_change_required")
    return user


async def admin_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "admin_only")
    return user
```

`src/sage/services.py`:
```python
"""Builds every service once, at app start. Later tasks add lines here."""
from pathlib import Path
from types import SimpleNamespace

from sage.audit import AuditLog
from sage.auth import AuthService
from sage.db import Database
from sage.secretbox import SecretBox
from sage.settings_store import SettingsStore
from sage.util import utcnow


async def build_services(*, data_dir, key_dir, connector=None, providers=None, workflows=None, clock=None):
    clock = clock or utcnow
    data_dir, key_dir = Path(data_dir), Path(key_dir)
    db = Database(data_dir / "sage.db")
    await db.connect()
    box = SecretBox(key_dir / "master.key")
    audit = AuditLog(db)
    settings = SettingsStore(db, box, audit)
    auth = AuthService(db, audit, clock)
    return SimpleNamespace(db=db, box=box, audit=audit, settings=settings, auth=auth,
                           data_dir=data_dir, clock=clock, connector=connector,
                           providers=providers, workflow_classes=workflows)
```

`src/sage/routes/auth_routes.py`:
```python
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from sage.auth import AuthError
from sage.deps import current_user

router = APIRouter(prefix="/api/auth")


class Login(BaseModel):
    username: str
    password: str


class ChangePassword(BaseModel):
    old: str
    new: str


@router.post("/login")
async def login(body: Login, request: Request, response: Response):
    svc = request.app.state.services
    try:
        token = await svc.auth.login(body.username, body.password, request.client.host if request.client else "?")
    except AuthError as e:
        raise HTTPException(429 if e.code == "rate_limited" else 401, e.code)
    response.set_cookie("sage_session", token, httponly=True, samesite="lax", max_age=7 * 86400)
    return {"ok": True}


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("sage_session")
    if token:
        await request.app.state.services.auth.logout(token)
    response.delete_cookie("sage_session")
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(current_user)):
    return {k: user[k] for k in ("id", "username", "role", "must_change_password")}


@router.post("/change-password")
async def change_password(body: ChangePassword, request: Request, user: dict = Depends(current_user)):
    try:
        await request.app.state.services.auth.change_password(user["id"], body.old, body.new, user["username"])
    except AuthError as e:
        raise HTTPException(400, e.code)
    return {"ok": True}
```

`src/sage/routes/users.py`:
```python
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from sage.auth import AuthError
from sage.deps import admin_user

router = APIRouter(prefix="/api/users")


class NewUser(BaseModel):
    username: str
    password: str
    role: str = "user"


class UserPatch(BaseModel):
    role: str | None = None
    disabled: bool | None = None


class Reset(BaseModel):
    password: str


@router.get("")
async def list_users(request: Request, admin: dict = Depends(admin_user)):
    return await request.app.state.services.auth.list_users()


@router.post("")
async def create_user(body: NewUser, request: Request, admin: dict = Depends(admin_user)):
    try:
        uid = await request.app.state.services.auth.create_user(body.username, body.password, body.role, admin["username"])
    except AuthError as e:
        raise HTTPException(400, e.code)
    return {"id": uid}


@router.patch("/{user_id}")
async def patch_user(user_id: int, body: UserPatch, request: Request, admin: dict = Depends(admin_user)):
    auth = request.app.state.services.auth
    try:
        if body.role is not None:
            await auth.set_role(user_id, body.role, admin["username"])
        if body.disabled is not None:
            await auth.set_disabled(user_id, body.disabled, admin["username"])
    except AuthError as e:
        raise HTTPException(400, e.code)
    return {"ok": True}


@router.post("/{user_id}/reset-password")
async def reset_password(user_id: int, body: Reset, request: Request, admin: dict = Depends(admin_user)):
    try:
        await request.app.state.services.auth.reset_password(user_id, body.password, admin["username"])
    except AuthError as e:
        raise HTTPException(400, e.code)
    return {"ok": True}
```

`src/sage/app.py` (replace):
```python
"""FastAPI app factory. Services are built in lifespan (see services.py)."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from sage.routes import auth_routes, users
from sage.services import build_services


def create_app(*, data_dir=None, key_dir=None, connector=None, providers=None,
               workflows=None, env=None, clock=None) -> FastAPI:
    data_dir = data_dir or os.getenv("SAGE_DATA_DIR", ".data")
    key_dir = key_dir or os.getenv("SAGE_KEY_DIR", ".keys")

    @asynccontextmanager
    async def lifespan(app):
        svc = await build_services(data_dir=data_dir, key_dir=key_dir, connector=connector,
                                   providers=providers, workflows=workflows, clock=clock)
        app.state.services = svc
        await svc.auth.ensure_bootstrap_admin(os.environ if env is None else env)
        yield
        await svc.db.close()

    app = FastAPI(title="DXC Sage", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    for r in (auth_routes.router, users.router):
        app.include_router(r)
    return app
```
Create empty `src/sage/routes/__init__.py`.

- [ ] **Step 4: Run to verify it passes** — `uv run pytest tests/test_auth.py tests/test_health.py -q` — Expected: `6 passed`. (If `tests` is not importable, add an empty `tests/__init__.py`; it was created in Task 0.)

---

### Task 4: SAP RFC service (PyRFC only) and `read_table`

**Files:**
- Create: `sage_api/src/sage/sap/{__init__.py,rfc.py}`, `sage_api/tests/test_rfc.py`
- Modify: `sage_api/tests/fakes.py` (full fake), `sage_api/tests/conftest.py` (add `rfc` fixture)

**Interfaces:**
- Consumes: `SettingsStore.get("sap.rowcount_cap")`.
- Produces: `RfcError(code, message)` (codes `CONNECT LOGIN TABLE_NOT_AVAILABLE AUTH FM_NOT_FOUND ABAP UNSTABLE_ORDER TOO_WIDE NO_ORDER WHERE_TOO_LONG`); `RfcParams(ashost, sysnr, client, user, passwd)`; `SapRfc(load_params, connector, settings)` with `async call(system_id, fm, **params) -> dict`, `ping(system_id)`, `read_table(system_id, table, fields, where="", rows=None) -> TableResult`, `probe_table(system_id, table)`, `drop(system_id)`, `test(params)`; `TableResult(rows: list[dict[str,str]], truncated: bool)`; `split_where(where) -> list[{"TEXT": str}]`; `classify_abap_key(key) -> str`; `pyrfc_connector(params)`.

- [ ] **Step 1: Write the fake and the failing tests**

`tests/fakes.py` (replace):
```python
import re

from sage.sap.rfc import RfcError


class FakeRfcClient:
    """Stands in for pyrfc. Implements RFC_READ_TABLE over in-memory tables."""

    def __init__(self, tables=None, lengths=None, functions=None):
        self.tables = tables or {}        # table -> list[dict]
        self.lengths = lengths or {}      # table -> {field: length}
        self.functions = functions or {}  # fm -> callable(**params) -> dict
        self.calls = []                   # (fm, params)
        self.unstable = False             # reverse row order on every other read

    def call(self, fm, **p):
        self.calls.append((fm, p))
        if fm == "RFC_PING":
            return {}
        if fm == "RFC_READ_TABLE":
            return self._read(p)
        if fm in self.functions:
            return self.functions[fm](**p)
        raise RfcError("FM_NOT_FOUND", fm)

    def close(self):
        pass

    def count(self, fm):
        return sum(1 for f, _ in self.calls if f == fm)

    def _read(self, p):
        t = p["QUERY_TABLE"]
        if t not in self.tables:
            raise RfcError("TABLE_NOT_AVAILABLE", t)
        names = [f["FIELDNAME"] for f in p.get("FIELDS", [])] or list(self.lengths[t])
        meta = [{"FIELDNAME": n, "LENGTH": self.lengths[t][n]} for n in names]
        if p.get("NO_DATA") == "X":
            return {"FIELDS": meta, "DATA": []}
        where = "".join(o["TEXT"] for o in p.get("OPTIONS", []))
        rows = [r for r in self.tables[t] if self._match(r, where)]
        if self.unstable and self.count("RFC_READ_TABLE") % 2 == 0:
            rows = list(reversed(rows))
        skip, count = p.get("ROWSKIPS", 0), p.get("ROWCOUNT", 0)
        rows = rows[skip: skip + count if count else None]
        data = [{"WA": "|".join(str(r.get(n, "")).ljust(self.lengths[t][n]) for n in names)} for r in rows]
        return {"FIELDS": meta, "DATA": data}

    @staticmethod
    def _match(row, where):
        if not where.strip():
            return True

        def ok(cond):
            m = re.fullmatch(r"(\w+) = '([^']*)'", cond.strip())
            return bool(m) and str(row.get(m[1], "")).strip() == m[2]

        return any(all(ok(c) for c in re.split(r"\s+AND\s+", part)) for part in re.split(r"\s+OR\s+", where.strip()))
```

Append to `tests/conftest.py`:
```python
from sage.sap.rfc import RfcParams, SapRfc


@pytest_asyncio.fixture
async def rfc(settings_store, fake_rfc):
    async def load(system_id):
        return RfcParams("host", "00", "100", "RFCUSER", "pw")
    return SapRfc(load, lambda p: fake_rfc, settings_store)
```

`tests/test_rfc.py`:
```python
import pytest
from sage.sap.rfc import RfcError, classify_abap_key, split_where

DD03L = [
    {"TABNAME": "ZWIDE", "FIELDNAME": "MANDT", "POSITION": "1", "KEYFLAG": "X"},
    {"TABNAME": "ZWIDE", "FIELDNAME": "ID", "POSITION": "2", "KEYFLAG": "X"},
    {"TABNAME": "ZWIDE", "FIELDNAME": "A", "POSITION": "3", "KEYFLAG": ""},
    {"TABNAME": "ZWIDE", "FIELDNAME": "B", "POSITION": "4", "KEYFLAG": ""},
]


def wide_fake(fake):
    fake.tables["DD03L"] = DD03L
    fake.lengths["DD03L"] = {"TABNAME": 30, "FIELDNAME": 30, "POSITION": 4, "KEYFLAG": 1}
    fake.lengths["ZWIDE"] = {"MANDT": 3, "ID": 10, "A": 300, "B": 300}
    fake.tables["ZWIDE"] = [{"MANDT": "100", "ID": str(i), "A": f"a{i}", "B": f"b{i}"} for i in range(3)]


def test_split_where_keeps_tokens_and_limit():
    w = " AND ".join(f"FIELD{i} = 'VALUE{i}'" for i in range(12))
    lines = [l["TEXT"] for l in split_where(w)]
    assert all(len(l) <= 72 for l in lines) and " ".join(x.strip() for x in lines) == w
    with pytest.raises(RfcError) as e:
        split_where("X" * 80)
    assert e.value.code == "WHERE_TOO_LONG"


def test_classify():
    assert classify_abap_key("TABLE_NOT_AVAILABLE") == "TABLE_NOT_AVAILABLE"
    assert classify_abap_key("FU_NOT_FOUND") == "FM_NOT_FOUND"
    assert classify_abap_key("NO_AUTHORIZATION") == "AUTH"
    assert classify_abap_key("OTHER") == "ABAP"


async def test_read_table_single_call(rfc, fake_rfc):
    fake_rfc.tables["T"] = [{"A": "1", "B": "x"}, {"A": "2", "B": "y"}]
    fake_rfc.lengths["T"] = {"A": 5, "B": 5}
    r = await rfc.read_table(1, "T", ["A", "B"], "B = 'y'")
    assert r.rows == [{"A": "2", "B": "y"}] and r.truncated is False


async def test_read_table_truncated(rfc, fake_rfc, settings_store):
    await settings_store.set("sap.rowcount_cap", 2, "t")
    fake_rfc.tables["T"] = [{"A": str(i)} for i in range(5)]
    fake_rfc.lengths["T"] = {"A": 5}
    r = await rfc.read_table(1, "T", ["A"])
    assert len(r.rows) == 2 and r.truncated is True


async def test_read_table_wide_fields_split_and_merged_by_key(rfc, fake_rfc):
    wide_fake(fake_rfc)
    r = await rfc.read_table(1, "ZWIDE", ["A", "B"])
    assert r.rows[1] == {"A": "a1", "B": "b1"}
    reads = [p for f, p in fake_rfc.calls if f == "RFC_READ_TABLE" and p["QUERY_TABLE"] == "ZWIDE" and p.get("NO_DATA") != "X"]
    assert len(reads) == 2                                   # A and B cannot share one 512-byte row


async def test_unstable_order_rejected(rfc, fake_rfc, settings_store):
    wide_fake(fake_rfc)
    await settings_store.set("sap.rowcount_cap", 2, "t")      # truncated window differs per batch
    fake_rfc.unstable = True
    with pytest.raises(RfcError) as e:
        await rfc.read_table(1, "ZWIDE", ["A", "B"])
    assert e.value.code == "UNSTABLE_ORDER"


async def test_probe_and_error_passthrough(rfc, fake_rfc):
    with pytest.raises(RfcError) as e:
        await rfc.probe_table(1, "NOPE")
    assert e.value.code == "TABLE_NOT_AVAILABLE"
    fake_rfc.tables["T"] = [{"A": "1"}]
    fake_rfc.lengths["T"] = {"A": 5}
    await rfc.probe_table(1, "T")


async def test_connection_cached_per_system_and_dropped(rfc, fake_rfc):
    await rfc.ping(1)
    await rfc.ping(2)
    assert set(rfc._clients) == {1, 2} and fake_rfc.count("RFC_PING") == 2
    rfc.drop(1)
    assert set(rfc._clients) == {2}
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_rfc.py -q` — FAIL `ModuleNotFoundError: sage.sap`.

- [ ] **Step 3: Implement**

`src/sage/sap/__init__.py`: empty. `src/sage/sap/rfc.py`:
```python
"""SAP access: PyRFC only. Reads use RFC_READ_TABLE; everything else is a named function module.

Not verified against a real SAP system from this repo: pyrfc_connector and the error mapping.
"""
import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

from pydantic import BaseModel

MAX_ROW = 512


class RfcError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


@dataclass(frozen=True)
class RfcParams:
    ashost: str
    sysnr: str
    client: str
    user: str
    passwd: str


class RfcClient(Protocol):
    def call(self, fm: str, **params) -> dict: ...
    def close(self) -> None: ...


class TableResult(BaseModel):
    rows: list[dict[str, str]]
    truncated: bool


def classify_abap_key(key: str) -> str:
    k = key.upper()
    if k in ("TABLE_NOT_AVAILABLE", "TABLE_WITHOUT_DATA"):
        return "TABLE_NOT_AVAILABLE"
    if k in ("FU_NOT_FOUND", "FUNCTION_NOT_FOUND"):
        return "FM_NOT_FOUND"
    if "AUTH" in k:
        return "AUTH"
    return "ABAP"


def split_where(where: str, width: int = 72) -> list[dict]:
    """OPTIONS lines are 72 chars; split on spaces and keep a trailing space as the joiner."""
    lines, cur = [], ""
    for tok in where.split():
        if len(tok) > width:
            raise RfcError("WHERE_TOO_LONG", tok)
        if cur and len(cur) + 1 + len(tok) > width:
            lines.append(cur + " ")
            cur = tok
        else:
            cur = f"{cur} {tok}" if cur else tok
    if cur:
        lines.append(cur)
    return [{"TEXT": line} for line in lines]


class _PyrfcClient:
    def __init__(self, conn, pyrfc):
        self._conn, self._p = conn, pyrfc

    def call(self, fm, **params):
        p = self._p
        try:
            return self._conn.call(fm, **params)
        except (p.ABAPApplicationError, p.ABAPRuntimeError) as e:
            raise RfcError(classify_abap_key(getattr(e, "key", "")), getattr(e, "message", str(e))) from e
        except p.CommunicationError as e:
            raise RfcError("CONNECT", str(e)) from e

    def close(self):
        self._conn.close()


def pyrfc_connector(p: RfcParams) -> RfcClient:
    try:
        import pyrfc
    except ImportError as e:
        raise RfcError("CONNECT", "pyrfc / SAP NW RFC SDK is not installed in this image") from e
    try:
        conn = pyrfc.Connection(ashost=p.ashost, sysnr=p.sysnr, client=p.client, user=p.user, passwd=p.passwd)
    except pyrfc.LogonError as e:
        raise RfcError("LOGIN", str(e)) from e
    except (pyrfc.CommunicationError, pyrfc.RFCError) as e:
        raise RfcError("CONNECT", str(e)) from e
    return _PyrfcClient(conn, pyrfc)


class SapRfc:
    def __init__(self, load_params: Callable[[int], Awaitable[RfcParams]],
                 connector: Callable[[RfcParams], RfcClient], settings):
        self._load, self._connector, self._settings = load_params, connector, settings
        self._clients: dict[int, RfcClient] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def drop(self, system_id: int) -> None:
        c = self._clients.pop(system_id, None)
        if c:
            try:
                c.close()
            except Exception:
                pass

    async def call(self, system_id: int, fm: str, **params) -> dict:
        async with self._locks.setdefault(system_id, asyncio.Lock()):
            for attempt in (0, 1):
                client = self._clients.get(system_id)
                if client is None:
                    client = await asyncio.to_thread(self._connector, await self._load(system_id))
                    self._clients[system_id] = client
                try:
                    return await asyncio.to_thread(client.call, fm, **params)
                except RfcError as e:
                    if e.code == "CONNECT" and attempt == 0:
                        self.drop(system_id)
                        continue
                    raise
        raise RfcError("CONNECT", "unreachable")

    async def ping(self, system_id: int) -> None:
        await self.call(system_id, "RFC_PING")

    async def test(self, params: RfcParams) -> None:
        """Connect and ping without touching the cache (used when registering a system)."""
        client = await asyncio.to_thread(self._connector, params)
        try:
            await asyncio.to_thread(client.call, "RFC_PING")
        finally:
            await asyncio.to_thread(client.close)

    async def probe_table(self, system_id: int, table: str) -> None:
        """Read one value of one column: proves the table exists and the account may read it."""
        meta = await self.call(system_id, "RFC_READ_TABLE", QUERY_TABLE=table, NO_DATA="X")
        first = meta["FIELDS"][0]["FIELDNAME"]
        await self.call(system_id, "RFC_READ_TABLE", QUERY_TABLE=table, ROWCOUNT=1, DELIMITER="|",
                        FIELDS=[{"FIELDNAME": first}])

    async def _lengths(self, system_id, table, names) -> dict[str, int]:
        res = await self.call(system_id, "RFC_READ_TABLE", QUERY_TABLE=table, NO_DATA="X",
                              FIELDS=[{"FIELDNAME": n} for n in names])
        return {f["FIELDNAME"]: int(f["LENGTH"]) for f in res["FIELDS"]}

    async def _keys(self, system_id, table) -> list[str]:
        res = await self.call(
            system_id, "RFC_READ_TABLE", QUERY_TABLE="DD03L", DELIMITER="|",
            FIELDS=[{"FIELDNAME": "FIELDNAME"}, {"FIELDNAME": "POSITION"}],
            OPTIONS=split_where(f"TABNAME = '{table}' AND KEYFLAG = 'X'"))
        parsed = [[x.strip() for x in w["WA"].split("|")] for w in res["DATA"]]
        rows = sorted((int(v[1] or 0), v[0]) for v in parsed)
        keys = [name for _, name in rows if name != "MANDT" and not name.startswith(".")]
        if not keys:
            raise RfcError("NO_ORDER", f"{table} has no key fields; cannot split a wide read")
        return keys

    async def read_table(self, system_id: int, table: str, fields: list[str],
                         where: str = "", rows: int | None = None) -> TableResult:
        cap = int(await self._settings.get("sap.rowcount_cap"))
        limit = min(rows or cap, cap)
        opts = split_where(where)
        lengths = await self._lengths(system_id, table, fields)
        if sum(lengths.values()) + len(fields) <= MAX_ROW:
            batches, keys = [list(fields)], []
        else:
            keys = await self._keys(system_id, table)
            need = [k for k in keys if k not in lengths]
            if need:
                lengths.update(await self._lengths(system_id, table, need))
            keyw = sum(lengths[k] + 1 for k in keys)
            batches, cur, width = [], list(keys), keyw
            for f in (f for f in fields if f not in keys):
                if keyw + lengths[f] + 1 > MAX_ROW:
                    raise RfcError("TOO_WIDE", f"{table}.{f} plus the key does not fit in {MAX_ROW} bytes")
                if width + lengths[f] + 1 > MAX_ROW:
                    batches.append(cur)
                    cur, width = list(keys), keyw
                cur.append(f)
                width += lengths[f] + 1
            batches.append(cur)
        parsed = []
        for names in batches:
            res = await self.call(system_id, "RFC_READ_TABLE", QUERY_TABLE=table, DELIMITER="|",
                                  ROWCOUNT=limit + 1, FIELDS=[{"FIELDNAME": n} for n in names], OPTIONS=opts)
            parsed.append([dict(zip(names, (x.strip() for x in w["WA"].split("|")))) for w in res["DATA"]])
        truncated = len(parsed[0]) > limit
        parsed = [p[:limit] for p in parsed]
        if len(parsed) == 1:
            merged = parsed[0]
        else:
            kf = lambda r: tuple(r[k] for k in keys)  # noqa: E731
            base = {kf(r): dict(r) for r in parsed[0]}
            for other in parsed[1:]:
                if {kf(r) for r in other} != set(base):
                    raise RfcError("UNSTABLE_ORDER", f"{table}: batches returned different rows; narrow the fields")
                for r in other:
                    base[kf(r)].update(r)
            merged = list(base.values())
        return TableResult(rows=[{f: r[f] for f in fields} for r in merged], truncated=truncated)
```

- [ ] **Step 4: Run to verify it passes** — `uv run pytest tests/test_rfc.py -q` — Expected: `9 passed`. If `test_read_table_wide...` fails on the `_keys` parsing, fix the comprehension in `_keys` (it must yield `(position, fieldname)` pairs); do not loosen the test.

---

### Task 5: Systems registry (admin only)

**Files:**
- Create: `sage_api/src/sage/{systems.py,routes/systems_routes.py}`, `sage_api/tests/test_systems.py`
- Modify: `src/sage/services.py`, `src/sage/app.py`

**Interfaces:**
- Consumes: `SecretBox`, `AuditLog`, `SapRfc`, `RfcParams`, `RfcError`.
- Produces: `SystemsService(db, box, audit, rfc)` with `create(data: dict, actor) -> dict` (returns system plus `test`), `update(system_id, data, actor)`, `set_credentials(system_id, user, password, actor)`, `set_status(system_id, status, actor)`, `test(system_id) -> dict`, `list(only_active=False) -> list[dict]`, `get(system_id) -> dict | None`, `by_label(label) -> dict | None`, `load_params(system_id) -> RfcParams`. Public system dict never contains the password. `services.rfc` (SapRfc) and `services.systems` exist after this task.
- Routes: `GET /api/systems` (admin, all), `GET /api/systems/active` (any user: `[{id,label,sid}]`), `POST /api/systems`, `PATCH /api/systems/{id}`, `PUT /api/systems/{id}/credentials {user,password}`, `POST /api/systems/{id}/status {status}`, `POST /api/systems/{id}/test`.

- [ ] **Step 1: Write the failing tests** — `tests/test_systems.py`:
```python
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
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_systems.py -q` — FAIL (no `/api/systems`).

- [ ] **Step 3: Implement**

`src/sage/systems.py`:
```python
"""Registered SAP systems. Admin-only; never deleted, only disabled."""
from sage.sap.rfc import RfcError, RfcParams
from sage.util import iso

_PUBLIC = "id,label,sid,description,ashost,sysnr,client,rfc_user,status,created_at,updated_at"
_FIELDS = ("label", "sid", "description", "ashost", "sysnr", "client", "rfc_user")


class SystemsError(Exception):
    pass


class SystemsService:
    def __init__(self, db, box, audit, rfc):
        self._db, self._box, self._audit, self._rfc = db, box, audit, rfc

    async def get(self, system_id):
        return await self._db.fetchone(f"SELECT {_PUBLIC} FROM systems WHERE id=?", (system_id,))

    async def by_label(self, label):
        return await self._db.fetchone(f"SELECT {_PUBLIC} FROM systems WHERE label=?", (label,))

    async def list(self, only_active=False):
        sql = f"SELECT {_PUBLIC} FROM systems" + (" WHERE status='active'" if only_active else "") + " ORDER BY label"
        return await self._db.fetchall(sql)

    async def load_params(self, system_id) -> RfcParams:
        r = await self._db.fetchone("SELECT * FROM systems WHERE id=?", (system_id,))
        return RfcParams(r["ashost"], r["sysnr"], r["client"], r["rfc_user"], self._box.decrypt(r["rfc_password_enc"]))

    async def test(self, system_id) -> dict:
        try:
            await self._rfc.test(await self.load_params(system_id))
        except RfcError as e:
            return {"ok": False, "stage": "login" if e.code == "LOGIN" else "connect", "message": e.message}
        return {"ok": True, "stage": None, "message": ""}

    async def create(self, data: dict, actor) -> dict:
        if await self.by_label(data["label"]):
            raise SystemsError("label_taken")
        now = iso()
        sid = await self._db.execute(
            "INSERT INTO systems(label,sid,description,ashost,sysnr,client,rfc_user,rfc_password_enc,status,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,'inactive',?,?)",
            (*(data.get(f, "") for f in _FIELDS), self._box.encrypt(data["rfc_password"]), now, now))
        await self._audit.write("system.create", actor, detail={k: data.get(k) for k in _FIELDS})
        result = await self.test(sid)
        if result["ok"]:
            await self._db.execute("UPDATE systems SET status='active', updated_at=? WHERE id=?", (iso(), sid))
        await self._audit.write("system.health_check", actor, detail={"system_id": sid, **result})
        return {**await self.get(sid), "test": result}

    async def update(self, system_id, data: dict, actor):
        sets = {k: v for k, v in data.items() if k in _FIELDS and v is not None}
        if sets:
            cols = ", ".join(f"{k}=?" for k in sets)
            await self._db.execute(f"UPDATE systems SET {cols}, updated_at=? WHERE id=?", (*sets.values(), iso(), system_id))
            self._rfc.drop(system_id)
            await self._audit.write("system.update", actor, detail={"system_id": system_id, **sets})

    async def set_credentials(self, system_id, user, password, actor):
        await self._db.execute("UPDATE systems SET rfc_user=?, rfc_password_enc=?, updated_at=? WHERE id=?",
                               (user, self._box.encrypt(password), iso(), system_id))
        self._rfc.drop(system_id)
        await self._audit.write("system.credentials", actor, detail={"system_id": system_id, "rfc_user": user})

    async def set_status(self, system_id, status, actor):
        if status not in ("inactive", "active", "disabled"):
            raise SystemsError("bad_status")
        await self._db.execute("UPDATE systems SET status=?, updated_at=? WHERE id=?", (status, iso(), system_id))
        await self._audit.write("system.disable" if status == "disabled" else "system.update", actor,
                                detail={"system_id": system_id, "status": status})
```

`src/sage/routes/systems_routes.py`:
```python
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from sage.deps import admin_user, current_user
from sage.systems import SystemsError

router = APIRouter(prefix="/api/systems")


class NewSystem(BaseModel):
    label: str = Field(pattern=r"^[A-Za-z0-9_-]{1,20}$")
    sid: str = Field(pattern=r"^[A-Z0-9]{3}$")
    description: str = ""
    ashost: str = Field(min_length=1)
    sysnr: str = Field(pattern=r"^\d{2}$")
    client: str = Field(pattern=r"^\d{3}$")
    rfc_user: str = Field(min_length=1)
    rfc_password: str = Field(min_length=1)


class SystemPatch(BaseModel):
    label: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,20}$")
    sid: str | None = Field(default=None, pattern=r"^[A-Z0-9]{3}$")
    description: str | None = None
    ashost: str | None = None
    sysnr: str | None = Field(default=None, pattern=r"^\d{2}$")
    client: str | None = Field(default=None, pattern=r"^\d{3}$")


class Credentials(BaseModel):
    user: str = Field(min_length=1)
    password: str = Field(min_length=1)


class Status(BaseModel):
    status: str


@router.get("")
async def list_systems(request: Request, admin: dict = Depends(admin_user)):
    return await request.app.state.services.systems.list()


@router.get("/active")
async def active_systems(request: Request, user: dict = Depends(current_user)):
    return [{"id": s["id"], "label": s["label"], "sid": s["sid"]}
            for s in await request.app.state.services.systems.list(only_active=True)]


@router.post("")
async def create_system(body: NewSystem, request: Request, admin: dict = Depends(admin_user)):
    try:
        return await request.app.state.services.systems.create(body.model_dump(), admin["username"])
    except SystemsError as e:
        raise HTTPException(400, str(e))


@router.patch("/{system_id}")
async def update_system(system_id: int, body: SystemPatch, request: Request, admin: dict = Depends(admin_user)):
    await request.app.state.services.systems.update(system_id, body.model_dump(), admin["username"])
    return {"ok": True}


@router.put("/{system_id}/credentials")
async def credentials(system_id: int, body: Credentials, request: Request, admin: dict = Depends(admin_user)):
    await request.app.state.services.systems.set_credentials(system_id, body.user, body.password, admin["username"])
    return {"ok": True}


@router.post("/{system_id}/status")
async def status(system_id: int, body: Status, request: Request, admin: dict = Depends(admin_user)):
    try:
        await request.app.state.services.systems.set_status(system_id, body.status, admin["username"])
    except SystemsError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.post("/{system_id}/test")
async def test_system(system_id: int, request: Request, admin: dict = Depends(admin_user)):
    return await request.app.state.services.systems.test(system_id)
```

`services.py`: add imports `from sage.sap.rfc import SapRfc, pyrfc_connector` and `from sage.systems import SystemsService`; before the `return`, add:
```python
    holder = SimpleNamespace(systems=None)

    async def load_params(system_id):
        return await holder.systems.load_params(system_id)

    rfc = SapRfc(load_params, connector or pyrfc_connector, settings)
    systems = SystemsService(db, box, audit, rfc)
    holder.systems = systems
```
and add `rfc=rfc, systems=systems` to the returned namespace. `app.py`: import `systems_routes` and add it to the router tuple.

- [ ] **Step 4: Run to verify it passes** — `uv run pytest tests/test_systems.py -q` — Expected: `6 passed`.

---

### Task 6: Requirements, tasks, workflows, durable context

**Files:**
- Create: `sage_api/src/sage/sap/requirements.py`, `src/sage/tasks/{__init__.py,base.py}`, `src/sage/workflows/{__init__.py,base.py}`, `src/sage/runtime/{__init__.py,errors.py,context.py}`, `tests/{test_requirements.py,test_context.py}`

**Interfaces:**
- Produces (requirements): `CheckResult(status, message)`, `CheckEnv(rfc, system_id, rfc_user, binding, settings, ping_error=None)`, `Requirement(key="", guide="", source=None)` with `kind`, `async check(env)`, `auth_rows() -> list[tuple[str,str,str]]`, `title() -> str`; subclasses `Reachable`, `LoginOk`, `FmExists(key)`, `FmAuthorized(key, group="")`, `TableReadable(key)`, `SettingPresent(key, scope="binding", level="fail")`.
- Produces (base): `Task` (`name`, `Input`, `Output`, `requirements`, `idempotent=True`, `async run(ctx, data)`), `TaskContext(system_id, rfc, settings, binding, data_dir, system_label="")`; `Workflow` (`name`, `description`, `Input`, `Output`, `durable=False`, `tasks`, `extra_requirements`, `binding_settings`, classmethod `requirements() -> list[Requirement]`, `async run(ctx, data)`), `SystemInput(system_name: str)`, `SettingSpec(key, label, required=False, description="")`.
- Produces (runtime): errors `WorkflowFailed`, `WorkflowSuspended(resume_at)`, `WaitTimeout`, `RunCancelled`, `AmbiguousStep`; `WorkflowContext(*, db, audit, run_id, tool_call_id, workflow, actor, task_ctx, backoff, max_wait, clock=utcnow, is_cancelled=None, emit=None)` with `async task(task_cls, data)`, `async wait(task_cls, data, until, *, backoff=None, max_wait=None)`, `async snapshot(name, fn)`; `delay_for(elapsed_seconds, schedule) -> int`.

- [ ] **Step 1: Write the failing tests**

`tests/test_requirements.py`:
```python
from sage.sap.requirements import (CheckEnv, FmAuthorized, FmExists, LoginOk, Reachable, SettingPresent, TableReadable)
from sage.sap.rfc import RfcError


def env(rfc, settings, **kw):
    return CheckEnv(rfc=rfc, system_id=1, rfc_user="RFCU", binding=kw.pop("binding", {}), settings=settings, **kw)


async def test_reachable_and_login(rfc, settings_store):
    assert (await Reachable().check(env(rfc, settings_store))).status == "pass"
    down = env(rfc, settings_store, ping_error=RfcError("CONNECT", "no route"))
    assert (await Reachable().check(down)).status == "fail"
    assert (await LoginOk().check(down)).status == "blocked"
    bad = env(rfc, settings_store, ping_error=RfcError("LOGIN", "denied"))
    assert (await Reachable().check(bad)).status == "pass"
    assert (await LoginOk().check(bad)).status == "fail"


async def test_fm_exists(rfc, settings_store, fake_rfc):
    fake_rfc.tables["TFDIR"] = [{"FUNCNAME": "ZFM_A"}]
    fake_rfc.lengths["TFDIR"] = {"FUNCNAME": 30}
    assert (await FmExists("ZFM_A").check(env(rfc, settings_store))).status == "pass"
    assert (await FmExists("ZFM_B").check(env(rfc, settings_store))).status == "fail"


async def test_fm_authorized_heuristic_and_unknown(rfc, settings_store, fake_rfc):
    vals = lambda **_: {"VALUES": [  # noqa: E731
        {"FIELD": "RFC_TYPE", "VON": "FUNC", "BIS": ""}, {"FIELD": "RFC_NAME", "VON": "ZFG_*", "BIS": ""},
        {"FIELD": "ACTVT", "VON": "16", "BIS": ""}]}
    fake_rfc.functions["SUSR_USER_AUTH_FOR_OBJ_GET"] = vals
    assert (await FmAuthorized("ZFM_X", group="ZFG_A").check(env(rfc, settings_store))).status == "pass"
    assert (await FmAuthorized("OTHER_FM").check(env(rfc, settings_store))).status == "fail"
    del fake_rfc.functions["SUSR_USER_AUTH_FOR_OBJ_GET"]
    assert (await FmAuthorized("ZFM_X").check(env(rfc, settings_store))).status == "warn"   # cannot verify


async def test_table_readable_and_setting(rfc, settings_store, fake_rfc):
    assert (await TableReadable("NOPE").check(env(rfc, settings_store))).status == "fail"
    fake_rfc.tables["T"], fake_rfc.lengths["T"] = [{"A": "1"}], {"A": 5}
    assert (await TableReadable("T").check(env(rfc, settings_store))).status == "pass"
    assert (await SettingPresent("default_variant").check(env(rfc, settings_store))).status == "fail"
    assert (await SettingPresent("default_variant", level="warn").check(env(rfc, settings_store))).status == "warn"
    assert (await SettingPresent("default_variant").check(env(rfc, settings_store, binding={"default_variant": "V1"}))).status == "pass"


def test_auth_rows():
    assert ("S_RFC", "RFC_NAME", "ZFM_X") in FmAuthorized("ZFM_X").auth_rows()
    assert ("S_TABU_NAM", "TABLE", "VARID") in TableReadable("VARID").auth_rows()
```

`tests/test_context.py`:
```python
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import BaseModel

from sage.runtime.context import WorkflowContext, delay_for
from sage.runtime.errors import AmbiguousStep, WaitTimeout, WorkflowSuspended
from sage.tasks.base import Task, TaskContext


class In(BaseModel):
    n: int = 0


class Out(BaseModel):
    v: int


CALLS = {"write": 0, "poll": 0}


class WriteTask(Task):
    name, Input, Output, idempotent = "t.write", In, Out, False

    async def run(self, ctx, data):
        CALLS["write"] += 1
        return Out(v=1)


class PollTask(Task):
    name, Input, Output = "t.poll", In, Out

    async def run(self, ctx, data):
        CALLS["poll"] += 1
        return Out(v=CALLS["poll"])


class Clock:
    def __init__(self):
        self.t = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        return self.t


BACKOFF = [[60, 10], [300, 60]]


async def make(db, audit, clock, rfc, settings_store, tool_call_id=1):
    await db.execute("INSERT OR IGNORE INTO users(id,username,password_hash,role,created_at) VALUES(1,'u','x','user','t')")
    await db.execute("INSERT OR IGNORE INTO chats(id,user_id,title,provider,model,created_at) VALUES(1,1,'c','p','m','t')")
    await db.execute("INSERT OR IGNORE INTO runs(id,chat_id,user_id,provider,model,status,started_at) VALUES(1,1,1,'p','m','running','t')")
    await db.execute("INSERT OR IGNORE INTO tool_calls(id,run_id,provider_call_id,workflow,input,status,started_at) VALUES(1,1,'c1','wf','{}','running','t')")
    tc = TaskContext(system_id=1, rfc=rfc, settings=settings_store, binding={}, data_dir=None)
    return WorkflowContext(db=db, audit=audit, run_id=1, tool_call_id=tool_call_id, workflow="wf", actor="u",
                           task_ctx=tc, backoff=BACKOFF, max_wait=3600, clock=clock)


def test_delay_for():
    assert delay_for(5, BACKOFF) == 10 and delay_for(100, BACKOFF) == 60 and delay_for(9999, BACKOFF) == 60


async def test_task_is_memoized_on_replay(db, audit, rfc, settings_store):
    CALLS.update(write=0, poll=0)
    clock = Clock()
    ctx = await make(db, audit, clock, rfc, settings_store)
    assert (await ctx.task(WriteTask, In())).v == 1
    ctx2 = await make(db, audit, clock, rfc, settings_store)          # replay: new context, same tool_call
    assert (await ctx2.task(WriteTask, In())).v == 1
    assert CALLS["write"] == 1


async def test_interrupted_non_idempotent_step_is_ambiguous(db, audit, rfc, settings_store):
    clock = Clock()
    ctx = await make(db, audit, clock, rfc, settings_store)
    await db.execute("INSERT INTO tool_steps(tool_call_id,seq,kind,attempt,name,workflow,input,status,created_at) "
                     "VALUES(1,1,'task',0,'t.write','wf','{}','running','t')")
    with pytest.raises(AmbiguousStep):
        await ctx.task(WriteTask, In())


async def test_wait_suspends_resumes_and_never_repeats_earlier_steps(db, audit, rfc, settings_store):
    CALLS.update(write=0, poll=0)
    clock = Clock()
    result = None
    for round_ in range(3):                                           # 3 resumes, like 3 scheduler wake-ups
        ctx = await make(db, audit, clock, rfc, settings_store)
        await ctx.task(WriteTask, In())
        try:
            result = await ctx.wait(PollTask, In(), until=lambda o: o.v >= 3)
            break
        except WorkflowSuspended as s:
            assert s.resume_at == clock.t + timedelta(seconds=10)
            clock.t = s.resume_at
    assert result.v == 3 and CALLS == {"write": 1, "poll": 3}
    ctx = await make(db, audit, clock, rfc, settings_store)           # replay after completion: no new calls
    await ctx.task(WriteTask, In())
    assert (await ctx.wait(PollTask, In(), until=lambda o: True)).v == 3
    assert CALLS == {"write": 1, "poll": 3}


async def test_wait_times_out(db, audit, rfc, settings_store):
    CALLS.update(write=0, poll=0)
    clock = Clock()
    ctx = await make(db, audit, clock, rfc, settings_store)
    with pytest.raises(WorkflowSuspended):
        await ctx.wait(PollTask, In(), until=lambda o: False)
    clock.t += timedelta(seconds=4000)
    ctx = await make(db, audit, clock, rfc, settings_store)
    with pytest.raises(WaitTimeout):
        await ctx.wait(PollTask, In(), until=lambda o: False)


async def test_snapshot_is_stable_across_replay(db, audit, rfc, settings_store):
    clock = Clock()
    box = {"v": 1}

    async def read():
        return {"v": box["v"]}

    ctx = await make(db, audit, clock, rfc, settings_store)
    assert await ctx.snapshot("cfg", read) == {"v": 1}
    box["v"] = 2
    ctx2 = await make(db, audit, clock, rfc, settings_store)
    assert await ctx2.snapshot("cfg", read) == {"v": 1}
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_requirements.py tests/test_context.py -q` — FAIL `ModuleNotFoundError: sage.sap.requirements`.

- [ ] **Step 3: Implement**

`src/sage/sap/requirements.py`:
```python
"""What a task or workflow needs from a SAP system. Checks are read-only: they never call a
write or job-scheduling function module. A pass proves existence and authorization, not that it works."""
import fnmatch
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel

from sage.sap.rfc import RfcError, SapRfc


class CheckResult(BaseModel):
    status: str                       # pass | warn | fail | blocked
    message: str = ""


@dataclass
class CheckEnv:
    rfc: SapRfc
    system_id: int
    rfc_user: str
    binding: dict
    settings: Any
    ping_error: RfcError | None = None


@dataclass(frozen=True)
class Requirement:
    key: str = ""
    guide: str = ""
    source: str | None = None         # file name under static/rfc/
    kind: ClassVar[str] = "base"

    async def check(self, env: CheckEnv) -> CheckResult:
        raise NotImplementedError

    def auth_rows(self) -> list[tuple[str, str, str]]:
        return []

    def title(self) -> str:
        return f"{self.kind}: {self.key}" if self.key else self.kind


@dataclass(frozen=True)
class Reachable(Requirement):
    kind: ClassVar[str] = "reachable"

    async def check(self, env):
        e = env.ping_error
        return CheckResult(status="fail", message=e.message) if e and e.code == "CONNECT" else CheckResult(status="pass")


@dataclass(frozen=True)
class LoginOk(Requirement):
    kind: ClassVar[str] = "login"

    async def check(self, env):
        e = env.ping_error
        if e is None:
            return CheckResult(status="pass")
        if e.code == "CONNECT":
            return CheckResult(status="blocked", message="system not reachable")
        return CheckResult(status="fail", message=e.message)


@dataclass(frozen=True)
class FmExists(Requirement):
    kind: ClassVar[str] = "fm_exists"

    async def check(self, env):
        try:
            r = await env.rfc.read_table(env.system_id, "TFDIR", ["FUNCNAME"], f"FUNCNAME = '{self.key}'", rows=1)
        except RfcError as e:
            return CheckResult(status="fail", message=f"cannot read TFDIR: {e.message}")
        return CheckResult(status="pass") if r.rows else CheckResult(status="fail", message="function module not found")

    def auth_rows(self):
        return [("S_TABU_NAM", "TABLE", "TFDIR"), ("S_TABU_NAM", "ACTVT", "03")]


@dataclass(frozen=True)
class FmAuthorized(Requirement):
    group: str = ""
    kind: ClassVar[str] = "fm_authorized"

    async def check(self, env):
        # Unverified: SUSR_USER_AUTH_FOR_OBJ_GET must be remote-enabled and allowed for the account.
        try:
            res = await env.rfc.call(env.system_id, "SUSR_USER_AUTH_FOR_OBJ_GET", USER_NAME=env.rfc_user, SAP_OBJECT="S_RFC")
        except RfcError as e:
            return CheckResult(status="warn", message=f"cannot verify S_RFC ({e.code}): {e.message}")
        vals: dict[str, list[str]] = {}
        for r in res.get("VALUES", []):
            vals.setdefault(r["FIELD"].strip(), []).append(r["VON"].strip())

        def allows(field_, wanted):
            return any(fnmatch.fnmatchcase(wanted, p) for p in vals.get(field_, []))

        names = [self.key] + ([self.group] if self.group else [])
        ok = allows("RFC_TYPE", "FUNC") and any(allows("RFC_NAME", n) for n in names) and allows("ACTVT", "16")
        return CheckResult(status="pass") if ok else CheckResult(
            status="fail", message=f"S_RFC does not cover FUNC {self.key} with ACTVT 16 (heuristic check)")

    def auth_rows(self):
        rows = [("S_RFC", "RFC_TYPE", "FUNC"), ("S_RFC", "RFC_NAME", self.key), ("S_RFC", "ACTVT", "16")]
        return rows + ([("S_RFC", "RFC_NAME", self.group)] if self.group else [])


@dataclass(frozen=True)
class TableReadable(Requirement):
    kind: ClassVar[str] = "table_readable"

    async def check(self, env):
        try:
            await env.rfc.probe_table(env.system_id, self.key)
        except RfcError as e:
            return CheckResult(status="fail", message=f"{e.code}: {e.message}")
        return CheckResult(status="pass")

    def auth_rows(self):
        return [("S_TABU_NAM", "TABLE", self.key), ("S_TABU_NAM", "ACTVT", "03")]


@dataclass(frozen=True)
class SettingPresent(Requirement):
    scope: str = "binding"            # "binding" = per-system workflow setting, "global" = settings table
    level: str = "fail"               # status when missing: fail | warn
    kind: ClassVar[str] = "setting"

    async def check(self, env):
        val = env.binding.get(self.key) if self.scope == "binding" else await env.settings.get(self.key)
        return CheckResult(status="pass") if val else CheckResult(status=self.level, message=f"setting '{self.key}' is not set")
```

`src/sage/tasks/__init__.py`: empty. `src/sage/tasks/base.py`:
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel

from sage.sap.requirements import Requirement
from sage.sap.rfc import SapRfc


@dataclass
class TaskContext:
    system_id: int | None
    rfc: SapRfc
    settings: Any
    binding: dict
    data_dir: Path | None
    system_label: str = ""


class Task(ABC):
    """One small independent operation. Knows nothing about which workflow calls it."""
    name: ClassVar[str]
    Input: ClassVar[type[BaseModel]]
    Output: ClassVar[type[BaseModel]]
    requirements: ClassVar[tuple[Requirement, ...]] = ()
    idempotent: ClassVar[bool] = True      # False = changes SAP; never re-run after an interrupted attempt

    @abstractmethod
    async def run(self, ctx: TaskContext, data: BaseModel) -> BaseModel: ...
```

`src/sage/workflows/__init__.py`: empty. `src/sage/workflows/base.py`:
```python
from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel

from sage.sap.requirements import LoginOk, Reachable, Requirement
from sage.tasks.base import Task


class SystemInput(BaseModel):
    system_name: str


class SettingSpec(BaseModel):
    key: str
    label: str
    required: bool = False
    description: str = ""


class Workflow(ABC):
    """The tool the model calls once. Runs fixed steps by calling shared tasks."""
    name: ClassVar[str]
    description: ClassVar[str]
    Input: ClassVar[type[BaseModel]]
    Output: ClassVar[type[BaseModel]]
    durable: ClassVar[bool] = False
    tasks: ClassVar[tuple[type[Task], ...]] = ()
    extra_requirements: ClassVar[tuple[Requirement, ...]] = ()
    binding_settings: ClassVar[tuple[SettingSpec, ...]] = ()

    @classmethod
    def requirements(cls) -> list[Requirement]:
        seen, out = set(), []
        for r in (Reachable(), LoginOk(), *[r for t in cls.tasks for r in t.requirements], *cls.extra_requirements):
            if (r.kind, r.key) not in seen:
                seen.add((r.kind, r.key))
                out.append(r)
        return out

    @abstractmethod
    async def run(self, ctx, data: BaseModel) -> BaseModel: ...
```

`src/sage/runtime/__init__.py`: empty. `src/sage/runtime/errors.py`:
```python
class WorkflowFailed(Exception):
    """A clean, user-visible failure. The message goes to the model."""


class WorkflowSuspended(Exception):
    def __init__(self, resume_at):
        super().__init__(f"suspended until {resume_at}")
        self.resume_at = resume_at


class WaitTimeout(WorkflowFailed):
    pass


class RunCancelled(Exception):
    pass


class AmbiguousStep(WorkflowFailed):
    """A step that changes SAP was interrupted; it is not repeated automatically."""
```

`src/sage/runtime/context.py`:
```python
"""Replayable workflow context. Every task call is a stored step; after a restart the workflow is
re-run from the top and finished steps return their stored result. Workflow code must call
ctx.task / ctx.wait / ctx.snapshot in the same order every time (no branching on live data)."""
import json
from datetime import timedelta

from sage.runtime.errors import AmbiguousStep, RunCancelled, WaitTimeout, WorkflowSuspended
from sage.util import iso, parse_iso, utcnow


def delay_for(elapsed: float, schedule) -> int:
    for threshold, interval in schedule:
        if elapsed < threshold:
            return interval
    return schedule[-1][1]


class WorkflowContext:
    def __init__(self, *, db, audit, run_id, tool_call_id, workflow, actor, task_ctx, backoff, max_wait,
                 clock=utcnow, is_cancelled=None, emit=None):
        self._db, self._audit, self.run_id, self.tool_call_id = db, audit, run_id, tool_call_id
        self.workflow, self.actor, self.task_ctx = workflow, actor, task_ctx
        self._backoff, self._max_wait, self._clock = backoff, max_wait, clock
        self._is_cancelled, self._emit = is_cancelled, emit
        self._seq = 0

    async def _guard(self):
        if self._is_cancelled and await self._is_cancelled():
            raise RunCancelled()

    async def _row(self, seq, kind, attempt=0):
        return await self._db.fetchone(
            "SELECT * FROM tool_steps WHERE tool_call_id=? AND seq=? AND kind=? AND attempt=?",
            (self.tool_call_id, seq, kind, attempt))

    async def _event(self, name, seq, kind, status):
        if self._emit:
            await self._emit("tool_step", {"workflow": self.workflow, "task": name, "seq": seq, "kind": kind, "status": status})

    async def _exec(self, task_cls, data, seq, kind, attempt=0):
        row = await self._row(seq, kind, attempt)
        if row and row["status"] == "running" and not task_cls.idempotent:
            raise AmbiguousStep(f"Step '{task_cls.name}' was interrupted and changes SAP; check the system before retrying.")
        if row is None:
            step_id = await self._db.execute(
                "INSERT INTO tool_steps(tool_call_id,seq,kind,attempt,name,workflow,input,status,created_at) VALUES(?,?,?,?,?,?,?,'running',?)",
                (self.tool_call_id, seq, kind, attempt, task_cls.name, self.workflow, data.model_dump_json(), iso(self._clock())))
        else:
            step_id = row["id"]
        await self._event(task_cls.name, seq, kind, "running")
        try:
            out = await task_cls().run(self.task_ctx, data)
        except Exception as e:
            await self._db.execute("UPDATE tool_steps SET status='error', error=? WHERE id=?", (str(e), step_id))
            await self._audit.write("tool.step", self.actor, self.run_id,
                                    {"workflow": self.workflow, "task": task_cls.name, "seq": seq, "status": "error", "error": str(e)})
            await self._event(task_cls.name, seq, kind, "error")
            raise
        await self._db.execute("UPDATE tool_steps SET status='ok', output=? WHERE id=?", (out.model_dump_json(), step_id))
        await self._audit.write("tool.step", self.actor, self.run_id,
                                {"workflow": self.workflow, "task": task_cls.name, "seq": seq, "status": "ok",
                                 "input": json.loads(data.model_dump_json()), "output": json.loads(out.model_dump_json())})
        await self._event(task_cls.name, seq, kind, "ok")
        return out

    async def task(self, task_cls, data):
        self._seq += 1
        row = await self._row(self._seq, "task")
        if row and row["status"] == "ok":
            return task_cls.Output.model_validate_json(row["output"])
        await self._guard()
        return await self._exec(task_cls, data, self._seq, "task")

    async def snapshot(self, name, fn):
        """Read live config once per run; replays see the same value."""
        self._seq += 1
        row = await self._row(self._seq, "snap")
        if row and row["status"] == "ok":
            return json.loads(row["output"])
        value = await fn()
        await self._db.execute(
            "INSERT OR REPLACE INTO tool_steps(tool_call_id,seq,kind,attempt,name,workflow,input,output,status,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,'ok',?)",
            (self.tool_call_id, self._seq, "snap", 0, name, self.workflow, "{}", json.dumps(value), iso(self._clock())))
        return value

    async def wait(self, task_cls, data, until, *, backoff=None, max_wait=None):
        """Poll a read-only task. One poll per entry; if not done, raise WorkflowSuspended so the
        scheduler wakes this run later. No coroutine stays blocked in memory."""
        self._seq += 1
        seq, now = self._seq, self._clock()
        backoff, max_wait = backoff or self._backoff, max_wait or self._max_wait
        wrow = await self._row(seq, "wait")
        if wrow and wrow["status"] == "ok":
            return task_cls.Output.model_validate_json(wrow["output"])
        if wrow is None:
            state = {"started_at": iso(now), "polls": 0}
            await self._db.execute(
                "INSERT INTO tool_steps(tool_call_id,seq,kind,attempt,name,workflow,input,status,created_at) VALUES(?,?,'wait',0,?,?,?,'running',?)",
                (self.tool_call_id, seq, task_cls.name, self.workflow, json.dumps(state), iso(now)))
        else:
            state = json.loads(wrow["input"])
        started = parse_iso(state["started_at"])
        if (now - started).total_seconds() > max_wait:
            await self._db.execute("UPDATE tool_steps SET status='error', error='timed_out' WHERE tool_call_id=? AND seq=? AND kind='wait'",
                                   (self.tool_call_id, seq))
            raise WaitTimeout(f"Gave up waiting for '{task_cls.name}' after {int(max_wait)} s.")
        await self._guard()
        out = await self._exec(task_cls, data, seq, "poll", attempt=state["polls"])
        state["polls"] += 1
        if until(out):
            await self._db.execute("UPDATE tool_steps SET status='ok', input=?, output=? WHERE tool_call_id=? AND seq=? AND kind='wait'",
                                   (json.dumps(state), out.model_dump_json(), self.tool_call_id, seq))
            return out
        await self._db.execute("UPDATE tool_steps SET input=? WHERE tool_call_id=? AND seq=? AND kind='wait'",
                               (json.dumps(state), self.tool_call_id, seq))
        raise WorkflowSuspended(now + timedelta(seconds=delay_for((now - started).total_seconds(), backoff)))
```

- [ ] **Step 4: Run to verify it passes** — `uv run pytest tests/test_requirements.py tests/test_context.py -q` — Expected: `12 passed`.

---

### Task 7: Health checks, workflow setup, guide, workflow registry

**Files:**
- Create: `sage_api/src/sage/{health.py,workflow_setup.py,guide.py}`, `src/sage/workflows/registry.py`, `src/sage/routes/workflow_routes.py`, `tests/test_health_setup.py`
- Modify: `src/sage/services.py`, `src/sage/app.py`

**Interfaces:**
- Consumes: `Workflow.requirements()`, `CheckEnv`, `SystemsService`, `SapRfc`, `SettingsStore`.
- Produces: `discover() -> dict[str, type[Workflow]]` (imports every module in `sage.workflows`, collects `Workflow` subclasses that define `name`). `HealthService(db, audit, rfc, systems, settings, workflows)` with `check(system_id, workflow, actor, binding=None) -> list[dict]`, `latest(system_id, workflow) -> list[dict]`, `overall(system_id, workflow) -> "pass"|"warn"|"fail"|"unknown"`, `ensure_fresh(system_id, workflow, actor) -> str`. `WorkflowSetupService(db, audit, systems, health, workflows, settings, clock)` with `setup(workflow, system_id, settings: dict, actor)`, `enable(workflow, system_id, actor)`, `disable(...)`, `bindings(workflow) -> list[dict]`, `enabled_systems(workflow) -> list[dict]`, `authorize_run(workflow, system_label, actor) -> tuple[dict, dict]` (system, binding settings); `SetupError(message)`, `AccessError(message)`. `build_guide(wf_cls, system, rows) -> dict`, `guide_markdown(guide) -> str`, `load_source(name) -> str`. Services: `services.workflows` (dict), `services.health`, `services.setup`.
- Routes: `GET /api/workflows` (any user; admin gets bindings too), `PUT /api/workflows/{name}/state {enabled}` (admin), `PUT /api/workflows/{name}/systems/{system_id} {settings}` (admin; creates or updates `setup`), `POST .../enable`, `POST .../disable`, `POST .../check`, `GET /api/workflows/{name}/systems/{system_id}/guide?format=json|markdown`, `GET /api/health/matrix`, `POST /api/health/recheck {system_id?}`.

- [ ] **Step 1: Write the failing tests** — `tests/test_health_setup.py`:
```python
import pytest
from pydantic import BaseModel

from sage.runtime.context import WorkflowContext  # noqa: F401  (import check)
from sage.sap.requirements import FmAuthorized, FmExists, SettingPresent, TableReadable
from sage.tasks.base import Task
from sage.workflows.base import SettingSpec, SystemInput, Workflow
from tests.conftest import login_admin


class Empty(BaseModel):
    pass


class UseTable(Task):
    name, Input, Output = "t.use", Empty, Empty
    requirements = (FmExists("ZFM_T", guide="Create ZFM_T in SE37 (remote-enabled).", source="ZFM_CHECK_JOB_STATUS.txt"),
                    FmAuthorized("ZFM_T"))

    async def run(self, ctx, data):
        return Empty()


class WfA(Workflow):
    name, description, Input, Output = "wf_a", "A", SystemInput, Empty
    tasks = (UseTable,)
    extra_requirements = (TableReadable("T1", guide="Allow reading T1."),
                          SettingPresent("default_variant", level="warn", guide="Set a default variant."))
    binding_settings = (SettingSpec(key="default_variant", label="Default variant"),)

    async def run(self, ctx, data):
        return Empty()


class WfB(Workflow):
    name, description, Input, Output = "wf_b", "B", SystemInput, Empty
    tasks = (UseTable,)

    async def run(self, ctx, data):
        return Empty()


@pytest.fixture
def app_kwargs():
    return {"workflows": {"wf_a": WfA, "wf_b": WfB}}


SYS = {"label": "TS3", "sid": "TS3", "description": "", "ashost": "h", "sysnr": "00", "client": "100",
       "rfc_user": "RFCU", "rfc_password": "pw-secret-1"}


def prepare_ok(fake):
    fake.tables["TFDIR"], fake.lengths["TFDIR"] = [{"FUNCNAME": "ZFM_T"}], {"FUNCNAME": 30}
    fake.tables["T1"], fake.lengths["T1"] = [{"A": "1"}], {"A": 5}
    fake.functions["SUSR_USER_AUTH_FOR_OBJ_GET"] = lambda **_: {"VALUES": [
        {"FIELD": "RFC_TYPE", "VON": "FUNC", "BIS": ""}, {"FIELD": "RFC_NAME", "VON": "*", "BIS": ""},
        {"FIELD": "ACTVT", "VON": "16", "BIS": ""}]}


async def mk_system(client):
    await login_admin(client)
    await client.post("/api/systems", json=SYS)


async def test_shared_task_requirements_deduped_per_workflow():
    keys = [(r.kind, r.key) for r in WfA.requirements()]
    assert keys == [("reachable", ""), ("login", ""), ("fm_exists", "ZFM_T"), ("fm_authorized", "ZFM_T"),
                    ("table_readable", "T1"), ("setting", "default_variant")]
    assert [(r.kind, r.key) for r in WfB.requirements()][-2:] == [("fm_exists", "ZFM_T"), ("fm_authorized", "ZFM_T")]


async def test_setup_check_enable_flow(client, fake_rfc):
    prepare_ok(fake_rfc)
    await mk_system(client)
    assert (await client.put("/api/workflows/wf_a/systems/1", json={"settings": {"default_variant": "V1"}})).status_code == 200
    rows = (await client.post("/api/workflows/wf_a/systems/1/check")).json()
    assert {r["status"] for r in rows} == {"pass"}
    assert (await client.post("/api/workflows/wf_a/systems/1/enable")).status_code == 200
    wf = {w["name"]: w for w in (await client.get("/api/workflows")).json()}
    assert wf["wf_a"]["bindings"][0]["status"] == "enabled" and wf["wf_b"]["bindings"] == []


async def test_enable_refused_when_requirement_fails(client, fake_rfc):
    prepare_ok(fake_rfc)
    del fake_rfc.tables["T1"]                                         # TableReadable fails
    await mk_system(client)
    await client.put("/api/workflows/wf_a/systems/1", json={"settings": {}})
    r = await client.post("/api/workflows/wf_a/systems/1/enable")
    assert r.status_code == 400 and "table_readable" in r.json()["detail"]


async def test_unreachable_blocks_dependents_and_never_calls_write_fms(client, fake_rfc, app):
    prepare_ok(fake_rfc)
    await mk_system(client)
    await client.put("/api/workflows/wf_b/systems/1", json={"settings": {}})
    from sage.sap.rfc import RfcError
    fake_rfc.functions["RFC_PING"] = None
    orig = fake_rfc.call

    def down(fm, **p):
        if fm == "RFC_PING":
            raise RfcError("CONNECT", "no route")
        return orig(fm, **p)
    fake_rfc.call = down
    app.state.services.rfc.drop(1)
    rows = (await client.post("/api/workflows/wf_b/systems/1/check")).json()
    st = {r["req_kind"]: r["status"] for r in rows}
    assert st["reachable"] == "fail" and st["login"] == "blocked" and st["fm_exists"] == "blocked"
    assert all(f in ("RFC_PING",) or f.startswith(("RFC_READ", "SUSR")) for f, _ in fake_rfc.calls)


async def test_run_authorization_requires_enabled_and_passing(client, fake_rfc, app):
    prepare_ok(fake_rfc)
    await mk_system(client)
    setup = app.state.services.setup
    from sage.workflow_setup import AccessError
    with pytest.raises(AccessError):
        await setup.authorize_run("wf_b", "TS3", "alice")             # not set up
    await client.put("/api/workflows/wf_b/systems/1", json={"settings": {}})
    with pytest.raises(AccessError):
        await setup.authorize_run("wf_b", "TS3", "alice")             # set up, not enabled
    await client.post("/api/workflows/wf_b/systems/1/enable")
    system, binding = await setup.authorize_run("wf_b", "TS3", "alice")
    assert system["label"] == "TS3" and binding == {}


async def test_guide_lists_steps_with_status_and_combined_auth_table(client, fake_rfc):
    prepare_ok(fake_rfc)
    await mk_system(client)
    await client.put("/api/workflows/wf_a/systems/1", json={"settings": {}})
    await client.post("/api/workflows/wf_a/systems/1/check")
    g = (await client.get("/api/workflows/wf_a/systems/1/guide")).json()
    step = next(s for s in g["steps"] if s["kind"] == "fm_exists")
    assert step["status"] == "pass" and "SE37" in step["text"] and "ZFM_CHECK_JOB_STATUS" in step["source_text"]
    assert ["S_RFC", "RFC_NAME", "ZFM_T"] in g["auth_table"] and g["system"]["rfc_user"] == "RFCU"
    md = (await client.get("/api/workflows/wf_a/systems/1/guide?format=markdown")).text
    assert "S_RFC" in md and "TS3" in md
```

(`ZFM_CHECK_JOB_STATUS.txt` is copied in Task 8, Step 1. Do Task 8 Step 1 first, or run this task's tests after it; the guide test needs that file. The ABAP copy is a non-code step.)

- [ ] **Step 2: Copy the ABAP specs now** (needed by the guide test)

Run (PowerShell, reads only the five `.txt` files from the user's zip into a new folder; nothing from the zip is executed):
```powershell
cd D:\User\Documents\Programming\Applications\DXCSage
New-Item -ItemType Directory -Force sage_api\src\sage\static\rfc | Out-Null
@'
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
b = "mcp_server/src/capabilities/sap_readiness_check/static/rfc/"
want = {b + n: n for n in ("ZFM_RC_START_ANALYSIS.txt", "ZFM_RC_NOTES_DOWNLOAD.txt", "ZFM_RC_FETCH_ANALYSIS.txt")}
want["mcp_server/src/static/rfc/ZFM_CHECK_JOB_STATUS.txt"] = "ZFM_CHECK_JOB_STATUS.txt"
for src, name in want.items():
    open(sys.argv[2] + "/" + name, "wb").write(z.read(src))
print(len(want), "files")
'@ | Set-Content -Encoding utf8 $env:TEMP\copy_rfc.py
python -I $env:TEMP\copy_rfc.py _references\mcp_architecture_PH.zip sage_api\src\sage\static\rfc
```
Expected: `4 files`. The ABAP text has non-ASCII dashes; `load_source` below reads with `errors="replace"`.

- [ ] **Step 3: Run to verify it fails** — `uv run pytest tests/test_health_setup.py -q` — FAIL `ModuleNotFoundError: sage.workflow_setup`.

- [ ] **Step 4: Implement**

`src/sage/workflows/registry.py`:
```python
import importlib
import pkgutil

import sage.workflows as pkg
from sage.workflows.base import Workflow


def discover() -> dict[str, type[Workflow]]:
    found = {}
    for m in pkgutil.iter_modules(pkg.__path__):
        if m.name in ("base", "registry"):
            continue
        mod = importlib.import_module(f"sage.workflows.{m.name}")
        for obj in vars(mod).values():
            if isinstance(obj, type) and issubclass(obj, Workflow) and obj is not Workflow and getattr(obj, "name", None):
                found[obj.name] = obj
    return found
```

`src/sage/health.py`:
```python
"""Per system and workflow health checks. Read-only; results stored in system_health."""
import json
from datetime import timedelta

from sage.sap.requirements import CheckEnv
from sage.sap.rfc import RfcError
from sage.util import iso, parse_iso, utcnow


class HealthService:
    def __init__(self, db, audit, rfc, systems, settings, workflows, clock=utcnow):
        self._db, self._audit, self._rfc, self._systems = db, audit, rfc, systems
        self._settings, self._workflows, self._clock = settings, workflows, clock

    async def check(self, system_id, workflow, actor, binding=None) -> list[dict]:
        system = await self._systems.get(system_id)
        if binding is None:
            row = await self._db.fetchone("SELECT settings FROM workflow_systems WHERE workflow=? AND system_id=?", (workflow, system_id))
            binding = json.loads(row["settings"]) if row else {}
        ping_error = None
        try:
            await self._rfc.ping(system_id)
        except RfcError as e:
            ping_error = e
        env = CheckEnv(self._rfc, system_id, system["rfc_user"], binding, self._settings, ping_error)
        reqs = self._workflows[workflow].requirements()
        now, out = iso(self._clock()), []
        blocked = ping_error is not None
        for r in reqs:
            if blocked and r.kind not in ("reachable", "login"):
                res_status, msg = "blocked", "system not reachable or login failed"
            else:
                res = await r.check(env)
                res_status, msg = res.status, res.message
            out.append({"system_id": system_id, "workflow": workflow, "req_kind": r.kind, "req_key": r.key,
                        "status": res_status, "message": msg, "checked_at": now})
        async with self._db.tx() as t:
            await t.execute("DELETE FROM system_health WHERE system_id=? AND workflow=?", (system_id, workflow))
            for o in out:
                await t.execute("INSERT INTO system_health(system_id,workflow,req_kind,req_key,status,message,checked_at) VALUES(?,?,?,?,?,?,?)",
                                (o["system_id"], o["workflow"], o["req_kind"], o["req_key"], o["status"], o["message"], now))
        await self._audit.write("system.health_check", actor, detail={
            "system_id": system_id, "workflow": workflow, "statuses": {f"{o['req_kind']}:{o['req_key']}": o["status"] for o in out}})
        return out

    async def latest(self, system_id, workflow) -> list[dict]:
        return await self._db.fetchall("SELECT * FROM system_health WHERE system_id=? AND workflow=? ORDER BY id", (system_id, workflow))

    @staticmethod
    def _overall(rows) -> str:
        if not rows:
            return "unknown"
        st = {r["status"] for r in rows}
        return "fail" if st & {"fail", "blocked"} else "warn" if "warn" in st else "pass"

    async def overall(self, system_id, workflow) -> str:
        return self._overall(await self.latest(system_id, workflow))

    async def ensure_fresh(self, system_id, workflow, actor) -> str:
        rows = await self.latest(system_id, workflow)
        max_age = int(await self._settings.get("health.max_age"))
        if not rows or self._clock() - parse_iso(rows[0]["checked_at"]) > timedelta(seconds=max_age):
            rows = await self.check(system_id, workflow, actor)
        return self._overall(rows)
```

`src/sage/workflow_setup.py`:
```python
"""A registered system is usable by a workflow only after an admin sets the workflow up on it."""
import json

from sage.util import iso, utcnow


class SetupError(Exception):
    pass


class AccessError(Exception):
    pass


class WorkflowSetupService:
    def __init__(self, db, audit, systems, health, workflows, settings, clock=utcnow):
        self._db, self._audit, self._systems, self._health = db, audit, systems, health
        self._workflows, self._settings, self._clock = workflows, settings, clock

    def _wf(self, name):
        if name not in self._workflows:
            raise SetupError("unknown_workflow")
        return self._workflows[name]

    async def setup(self, workflow, system_id, settings: dict, actor):
        wf = self._wf(workflow)
        system = await self._systems.get(system_id)
        if not system or system["status"] != "active":
            raise SetupError("system_not_active")
        allowed = {s.key for s in wf.binding_settings}
        clean = {k: v for k, v in settings.items() if k in allowed}
        now = iso(self._clock())
        await self._db.execute(
            "INSERT INTO workflow_systems(workflow,system_id,status,settings,created_at,updated_at) VALUES(?,?,'setup',?,?,?) "
            "ON CONFLICT(workflow,system_id) DO UPDATE SET settings=excluded.settings, updated_at=excluded.updated_at, "
            "status=CASE WHEN status='enabled' THEN 'enabled' ELSE 'setup' END",
            (workflow, system_id, json.dumps(clean), now, now))
        await self._audit.write("workflow.setup", actor, detail={"workflow": workflow, "system_id": system_id, "settings": clean})

    async def enable(self, workflow, system_id, actor):
        self._wf(workflow)
        row = await self._db.fetchone("SELECT * FROM workflow_systems WHERE workflow=? AND system_id=?", (workflow, system_id))
        if not row:
            raise SetupError("not_set_up")
        rows = await self._health.check(system_id, workflow, actor)
        bad = [f"{r['req_kind']}:{r['req_key']} {r['status']}" for r in rows if r["status"] in ("fail", "blocked")]
        if bad:
            raise SetupError("Cannot enable, failing requirements: " + "; ".join(bad))
        await self._db.execute("UPDATE workflow_systems SET status='enabled', enabled_by=?, updated_at=? WHERE id=?",
                               (actor, iso(self._clock()), row["id"]))
        await self._audit.write("workflow.enable", actor, detail={"workflow": workflow, "system_id": system_id})

    async def disable(self, workflow, system_id, actor):
        await self._db.execute("UPDATE workflow_systems SET status='disabled', updated_at=? WHERE workflow=? AND system_id=?",
                               (iso(self._clock()), workflow, system_id))
        await self._audit.write("workflow.disable", actor, detail={"workflow": workflow, "system_id": system_id})

    async def bindings(self, workflow) -> list[dict]:
        rows = await self._db.fetchall(
            "SELECT ws.system_id, s.label, s.sid, ws.status, ws.settings FROM workflow_systems ws "
            "JOIN systems s ON s.id=ws.system_id WHERE ws.workflow=? ORDER BY s.label", (workflow,))
        for r in rows:
            r["settings"] = json.loads(r["settings"])
            r["health"] = await self._health.overall(r["system_id"], workflow)
        return rows

    async def enabled_systems(self, workflow) -> list[dict]:
        """Systems offered to the model: enabled here, system active, last check pass or warn."""
        out = []
        for b in await self.bindings(workflow):
            sys_ = await self._systems.get(b["system_id"])
            if b["status"] == "enabled" and sys_["status"] == "active" and b["health"] in ("pass", "warn"):
                out.append(sys_)
        return out

    async def authorize_run(self, workflow, system_label, actor):
        if workflow in await self._settings.get("workflows.disabled"):
            raise AccessError(f"Workflow '{workflow}' is disabled.")
        system = await self._systems.by_label(system_label)
        row = system and await self._db.fetchone(
            "SELECT * FROM workflow_systems WHERE workflow=? AND system_id=?", (workflow, system["id"]))
        if not row or row["status"] != "enabled" or system["status"] != "active":
            raise AccessError(f"Workflow '{workflow}' is not enabled on system '{system_label}'.")
        health = await self._health.ensure_fresh(system["id"], workflow, actor)
        if health not in ("pass", "warn"):
            failed = [f"{r['req_kind']}:{r['req_key']}" for r in await self._health.latest(system["id"], workflow)
                      if r["status"] in ("fail", "blocked")]
            raise AccessError(f"Health check failed on '{system_label}': " + ", ".join(failed))
        return system, json.loads(row["settings"])
```

`src/sage/guide.py`:
```python
"""Setup guide for a workflow on a system. Generated from the declared requirements, never stored."""
from pathlib import Path

_RFC_DIR = Path(__file__).parent / "static" / "rfc"

_DEFAULT_GUIDE = {
    "reachable": "Make the application server reachable from the Sage host (network route, firewall, SAP router, sysnr).",
    "login": "Create a dialog or system RFC user in the client, with the password registered in Sage. Check for a locked or expired user.",
    "fm_exists": "Create the function module in SE37 (remote-enabled) in the function group and transport it to this system.",
    "fm_authorized": "Add S_RFC to the RFC user's role so the function (or its group) may be called remotely with ACTVT 16.",
    "table_readable": "Add S_TABU_NAM (or S_TABU_DIS for the table's authorization group) with ACTVT 03 for the table.",
    "setting": "Fill in this value on the workflow setup page.",
}


def load_source(name: str) -> str:
    return (_RFC_DIR / name).read_text(encoding="utf-8", errors="replace")


def build_guide(wf_cls, system: dict, rows: list[dict] | None) -> dict:
    status = {(r["req_kind"], r["req_key"]): r for r in rows or []}
    steps, auth, seen = [], [], set()
    for r in wf_cls.requirements():
        res = status.get((r.kind, r.key))
        steps.append({
            "kind": r.kind, "key": r.key, "title": r.title(),
            "text": (r.guide or _DEFAULT_GUIDE.get(r.kind, "")).replace("{sid}", system["sid"]).replace(
                "{client}", system["client"]).replace("{user}", system["rfc_user"]),
            "source": r.source, "source_text": load_source(r.source) if r.source else None,
            "status": res["status"] if res else None, "message": res["message"] if res else "",
        })
        for row in r.auth_rows():
            if row not in seen:
                seen.add(row)
                auth.append(list(row))
    return {"workflow": wf_cls.name, "description": wf_cls.description,
            "system": {k: system[k] for k in ("label", "sid", "client", "rfc_user")},
            "steps": steps, "auth_table": auth}


def guide_markdown(g: dict) -> str:
    s = g["system"]
    out = [f"# Setup guide: {g['workflow']} on {s['label']} ({s['sid']}, client {s['client']})", "",
           g["description"], "", f"RFC user: `{s['rfc_user']}`", "", "## Steps", ""]
    for i, st in enumerate(g["steps"], 1):
        flag = f" [{st['status']}]" if st["status"] else ""
        out += [f"{i}. **{st['title']}**{flag}", f"   {st['text']}"]
        if st["message"]:
            out.append(f"   Last check: {st['message']}")
        if st["source_text"]:
            out += ["", "```abap", st["source_text"], "```"]
    out += ["", "## Authorizations for the RFC user's role", "", "| Object | Field | Value |", "|---|---|---|"]
    out += [f"| {o} | {f} | {v} |" for o, f, v in g["auth_table"]]
    return "\n".join(out) + "\n"
```

`src/sage/routes/workflow_routes.py`:
```python
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from sage.deps import admin_user, current_user
from sage.guide import build_guide, guide_markdown
from sage.workflow_setup import AccessError, SetupError

router = APIRouter(prefix="/api")


class State(BaseModel):
    enabled: bool


class Settings(BaseModel):
    settings: dict = {}


class Recheck(BaseModel):
    system_id: int | None = None


def _svc(request):
    return request.app.state.services


@router.get("/workflows")
async def list_workflows(request: Request, user: dict = Depends(current_user)):
    svc = _svc(request)
    disabled = await svc.settings.get("workflows.disabled")
    out = []
    for name, cls in svc.workflows.items():
        item = {"name": name, "description": cls.description, "durable": cls.durable, "enabled": name not in disabled,
                "settings": [s.model_dump() for s in cls.binding_settings], "bindings": []}
        if user["role"] == "admin":
            item["bindings"] = await svc.setup.bindings(name)
        out.append(item)
    return out


@router.put("/workflows/{name}/state")
async def set_state(name: str, body: State, request: Request, admin: dict = Depends(admin_user)):
    svc = _svc(request)
    if name not in svc.workflows:
        raise HTTPException(404, "unknown_workflow")
    disabled = set(await svc.settings.get("workflows.disabled"))
    (disabled.discard if body.enabled else disabled.add)(name)
    await svc.settings.set("workflows.disabled", sorted(disabled), admin["username"])
    return {"ok": True}


async def _guard(coro):
    try:
        return await coro
    except (SetupError, AccessError) as e:
        raise HTTPException(400, str(e))


@router.put("/workflows/{name}/systems/{system_id}")
async def setup(name: str, system_id: int, body: Settings, request: Request, admin: dict = Depends(admin_user)):
    await _guard(_svc(request).setup.setup(name, system_id, body.settings, admin["username"]))
    return {"ok": True}


@router.post("/workflows/{name}/systems/{system_id}/enable")
async def enable(name: str, system_id: int, request: Request, admin: dict = Depends(admin_user)):
    await _guard(_svc(request).setup.enable(name, system_id, admin["username"]))
    return {"ok": True}


@router.post("/workflows/{name}/systems/{system_id}/disable")
async def disable(name: str, system_id: int, request: Request, admin: dict = Depends(admin_user)):
    await _svc(request).setup.disable(name, system_id, admin["username"])
    return {"ok": True}


@router.post("/workflows/{name}/systems/{system_id}/check")
async def check(name: str, system_id: int, request: Request, admin: dict = Depends(admin_user)):
    svc = _svc(request)
    if name not in svc.workflows:
        raise HTTPException(404, "unknown_workflow")
    return await svc.health.check(system_id, name, admin["username"])


@router.get("/workflows/{name}/systems/{system_id}/guide")
async def guide(name: str, system_id: int, request: Request, format: str = "json", admin: dict = Depends(admin_user)):
    svc = _svc(request)
    system = await svc.systems.get(system_id)
    if name not in svc.workflows or not system:
        raise HTTPException(404, "not_found")
    g = build_guide(svc.workflows[name], system, await svc.health.latest(system_id, name))
    return PlainTextResponse(guide_markdown(g)) if format == "markdown" else g


@router.get("/health/matrix")
async def matrix(request: Request, admin: dict = Depends(admin_user)):
    svc = _svc(request)
    systems = await svc.systems.list()
    cells = []
    for name in svc.workflows:
        for b in await svc.setup.bindings(name):
            cells.append({"workflow": name, "system_id": b["system_id"], "status": b["status"], "health": b["health"]})
    return {"systems": systems, "workflows": list(svc.workflows), "cells": cells}


@router.post("/health/recheck")
async def recheck(body: Recheck, request: Request, admin: dict = Depends(admin_user)):
    svc = _svc(request)
    for name in svc.workflows:
        for b in await svc.setup.bindings(name):
            if body.system_id in (None, b["system_id"]):
                await svc.health.check(b["system_id"], name, admin["username"])
    return {"ok": True}
```
`services.py`: add imports `from sage.health import HealthService`, `from sage.workflow_setup import WorkflowSetupService`, `from sage.workflows.registry import discover`; before the `return`:
```python
    wf = workflows if workflows is not None else discover()
    health = HealthService(db, audit, rfc, systems, settings, wf, clock)
    setup = WorkflowSetupService(db, audit, systems, health, wf, settings, clock)
```
and add `workflows=wf, health=health, setup=setup` to the namespace (keep `workflow_classes` removed). `app.py`: include `workflow_routes.router`.

- [ ] **Step 5: Run to verify it passes** — `uv run pytest tests/test_health_setup.py -q` — Expected: `6 passed`.

---

### Task 8: SAP tasks and the Readiness Check workflow

**Files:**
- Create: `sage_api/src/sage/tasks/{sap_read_table.py,sap_job_status.py,rc_notes_download.py,rc_start_analysis.py,rc_fetch_archive.py}`, `src/sage/workflows/sap_readiness_check.py`, `tests/test_readiness.py`

**Interfaces:**
- Consumes: `Task`, `TaskContext`, `Workflow`, `SystemInput`, `WorkflowContext`, requirements.
- Produces tasks (names are stored in steps): `sap.read_table` (`ReadTableIn(table, fields, where="", rows=None)` → `ReadTableOut(rows, truncated)`), `sap.job_status` (`JobStatusIn(job_name, job_count)` → `JobStatusOut(found, status_code, status_label, terminal, failed)`), `rc.notes_download` (`NotesDownloadIn(notes: list[str])` → `NotesDownloadOut(schedule_id, run_id, job_count, messages)`, non-idempotent), `rc.start_analysis` (`StartAnalysisIn(job_name, variant)` → `StartAnalysisOut(job_name, job_count)`, non-idempotent), `rc.fetch_archive` (`FetchArchiveIn(job_name, job_count)` → `FetchArchiveOut(file_path, filename, size_bytes)`).
- Produces workflow `sap_readiness_check` (`ReadinessInput(system_name, variant_name=None, job_name=None)` → `ReadinessOutput(job_name, job_count, final_status, file_path, filename, size_bytes, notes)`), `durable = True`.

- [ ] **Step 1: Write the failing tests** — `tests/test_readiness.py`:
```python
from datetime import datetime, timedelta, timezone

import pytest

from sage.runtime.context import WorkflowContext
from sage.runtime.errors import WorkflowFailed, WorkflowSuspended
from sage.tasks.base import TaskContext
from sage.workflows.sap_readiness_check import ReadinessInput, SapReadinessCheck


class Clock:
    def __init__(self):
        self.t = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        return self.t


def pad(n):
    return n.rjust(10, "0")


def sap_world(fake, *, missing=(), status_codes=("R", "F"), variants=("V1",)):
    notes = ["1668882", "2971435", "2758146", "2399707", "2903677", "2502552", "2781766"]
    have = [n for n in notes if n not in missing]
    fake.tables["CWBNTHEAD"], fake.lengths["CWBNTHEAD"] = [{"NUMM": pad(n)} for n in have], {"NUMM": 10}
    fake.tables["CWBNTCUST"] = [{"NUMM": pad(n), "PRSTATUS": "E"} for n in have]
    fake.lengths["CWBNTCUST"] = {"NUMM": 10, "PRSTATUS": 1}
    fake.tables["VARID"] = [{"REPORT": "RC_COLLECT_ANALYSIS_DATA", "VARIANT": v} for v in variants]
    fake.lengths["VARID"] = {"REPORT": 40, "VARIANT": 14}
    codes = iter(status_codes)
    last = {"c": status_codes[-1]}

    def job_status(**p):
        last["c"] = next(codes, last["c"])
        return {"STATUS": last["c"]}
    fake.functions["ZFM_CHECK_JOB_STATUS"] = job_status
    fake.functions["ZFM_RC_START_ANALYSIS"] = lambda **p: {"REAL_JOBNAME": p["JOBNAME"], "JOBCOUNT": "01234567"}
    fake.functions["ZFM_RC_FETCH_ANALYSIS"] = lambda **p: {"FILENAME": "rc.zip", "ZIP_DATA": b"PK\x03\x04data"}
    fake.functions["ZFM_RC_NOTES_DOWNLOAD"] = lambda **p: {"EV_SCHEDULE_ID": "S1", "EV_RUN_ID": "R1", "EV_JOB_COUNT": "01", "ET_RETURN": []}


async def make_ctx(db, audit, rfc, settings_store, tmp_path, clock, binding=None):
    await db.execute("INSERT OR IGNORE INTO users(id,username,password_hash,role,created_at) VALUES(1,'u','x','user','t')")
    await db.execute("INSERT OR IGNORE INTO chats(id,user_id,title,provider,model,created_at) VALUES(1,1,'c','p','m','t')")
    await db.execute("INSERT OR IGNORE INTO runs(id,chat_id,user_id,provider,model,status,started_at) VALUES(1,1,1,'p','m','running','t')")
    await db.execute("INSERT OR IGNORE INTO tool_calls(id,run_id,provider_call_id,workflow,input,status,started_at) VALUES(1,1,'c','sap_readiness_check','{}','running','t')")
    tc = TaskContext(1, rfc, settings_store, binding if binding is not None else {"default_variant": "V1"}, tmp_path, "TS3")
    return WorkflowContext(db=db, audit=audit, run_id=1, tool_call_id=1, workflow="sap_readiness_check", actor="u",
                           task_ctx=tc, backoff=[[60, 10], [300, 60]], max_wait=7200, clock=clock)


async def drive(db, audit, rfc, settings_store, tmp_path, clock, data, **kw):
    """Replay the workflow like the scheduler does, until it returns or fails."""
    for _ in range(20):
        ctx = await make_ctx(db, audit, rfc, settings_store, tmp_path, clock, **kw)
        try:
            return await SapReadinessCheck().run(ctx, data)
        except WorkflowSuspended as s:
            clock.t = s.resume_at
    raise AssertionError("did not finish")


async def test_happy_path_replays_without_rescheduling(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    sap_world(fake_rfc, status_codes=("R", "R", "F"))
    out = await drive(db, audit, rfc, settings_store, tmp_path, Clock(), ReadinessInput(system_name="TS3"))
    assert out.final_status == "finished" and out.filename == "rc.zip" and out.size_bytes == 8
    assert out.job_name == "RC_COLLECT_ANALYSIS_DATA" and out.job_count == "01234567"
    assert fake_rfc.count("ZFM_RC_START_ANALYSIS") == 1           # scheduled once despite replays
    assert (tmp_path / "downloads" / "TS3").exists()
    assert all(n.present and n.implemented for n in out.notes if not n.conditional)


async def test_missing_required_note_is_downloaded_then_proceeds(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    sap_world(fake_rfc, missing=("2903677",))
    orig = fake_rfc.functions["ZFM_RC_NOTES_DOWNLOAD"]

    def dl(**p):                                                   # the download makes the note appear
        fake_rfc.tables["CWBNTHEAD"].append({"NUMM": pad("2903677")})
        fake_rfc.tables["CWBNTCUST"].append({"NUMM": pad("2903677"), "PRSTATUS": "E"})
        return orig(**p)
    fake_rfc.functions["ZFM_RC_NOTES_DOWNLOAD"] = dl
    out = await drive(db, audit, rfc, settings_store, tmp_path, Clock(), ReadinessInput(system_name="TS3"))
    assert fake_rfc.count("ZFM_RC_NOTES_DOWNLOAD") == 1 and out.final_status == "finished"


async def test_note_never_arrives_fails_before_scheduling(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    sap_world(fake_rfc, missing=("2903677",))
    await settings_store.set("readiness.prerequisite_notes", {**(await settings_store.get("readiness.prerequisite_notes")),
                                                              "download_wait_seconds": 30, "download_poll_seconds": 10}, "t")
    with pytest.raises(WorkflowFailed, match="2903677"):
        await drive(db, audit, rfc, settings_store, tmp_path, Clock(), ReadinessInput(system_name="TS3"))
    assert fake_rfc.count("ZFM_RC_START_ANALYSIS") == 0


async def test_unknown_variant_and_no_variant_fail(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    sap_world(fake_rfc)
    with pytest.raises(WorkflowFailed, match="variant"):
        await drive(db, audit, rfc, settings_store, tmp_path, Clock(), ReadinessInput(system_name="TS3", variant_name="NOPE"))
    with pytest.raises(WorkflowFailed, match="variant"):
        await drive(db, audit, rfc, settings_store, tmp_path, Clock(), ReadinessInput(system_name="TS3"), binding={})


async def test_job_failure_reported(db, audit, rfc, settings_store, fake_rfc, tmp_path):
    sap_world(fake_rfc, status_codes=("R", "A"))
    with pytest.raises(WorkflowFailed, match="aborted"):
        await drive(db, audit, rfc, settings_store, tmp_path, Clock(), ReadinessInput(system_name="TS3"))


def test_requirements_include_tables_fms_and_shared_tasks():
    keys = {(r.kind, r.key) for r in SapReadinessCheck.requirements()}
    assert {("table_readable", "CWBNTHEAD"), ("table_readable", "VARID"), ("fm_exists", "ZFM_RC_START_ANALYSIS"),
            ("fm_exists", "ZFM_CHECK_JOB_STATUS"), ("fm_authorized", "ZFM_RC_FETCH_ANALYSIS")} <= keys
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_readiness.py -q` — FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement the tasks**

`src/sage/tasks/sap_read_table.py`:
```python
from pydantic import BaseModel

from sage.tasks.base import Task


class ReadTableIn(BaseModel):
    table: str
    fields: list[str]
    where: str = ""
    rows: int | None = None


class ReadTableOut(BaseModel):
    rows: list[dict[str, str]]
    truncated: bool


class ReadTable(Task):
    """Generic read through RFC_READ_TABLE. The calling workflow declares TableReadable for each table it reads."""
    name, Input, Output = "sap.read_table", ReadTableIn, ReadTableOut

    async def run(self, ctx, data):
        r = await ctx.rfc.read_table(ctx.system_id, data.table, data.fields, data.where, data.rows)
        return ReadTableOut(rows=r.rows, truncated=r.truncated)
```

`src/sage/tasks/sap_job_status.py`:
```python
from pydantic import BaseModel

from sage.sap.requirements import FmAuthorized, FmExists
from sage.sap.rfc import RfcError
from sage.tasks.base import Task

# BTCSTATUS. "X" mirrors the old watcher; "A" (aborted) is added here: both end the job unsuccessfully. Unverified on a live system.
LABELS = {"R": "running", "Y": "ready", "P": "scheduled", "S": "released", "F": "finished", "A": "aborted", "X": "failed"}
GUIDE = ("Create ZFM_CHECK_JOB_STATUS in SE37 (function group ZFG_MCPARCHPH, remote-enabled), wrapping "
         "BP_JOB_STATUS_GET. Skip it only if calling BP_JOB_STATUS_GET directly over RFC works in this system.")


class JobStatusIn(BaseModel):
    job_name: str
    job_count: str


class JobStatusOut(BaseModel):
    found: bool
    status_code: str = ""
    status_label: str = ""
    terminal: bool = False
    failed: bool = False


class JobStatus(Task):
    """Shared by any workflow that schedules a background job."""
    name, Input, Output = "sap.job_status", JobStatusIn, JobStatusOut
    requirements = (FmExists("ZFM_CHECK_JOB_STATUS", guide=GUIDE, source="ZFM_CHECK_JOB_STATUS.txt"),
                    FmAuthorized("ZFM_CHECK_JOB_STATUS", group="ZFG_MCPARCHPH"))

    async def run(self, ctx, data):
        try:
            res = await ctx.rfc.call(ctx.system_id, "ZFM_CHECK_JOB_STATUS", JOBNAME=data.job_name, JOBCOUNT=data.job_count)
        except RfcError as e:
            if "JOB_NOT_FOUND" in e.message or "JOB_NOT_FOUND" in e.code:
                return JobStatusOut(found=False)
            raise
        code = (res.get("STATUS") or "").strip()
        return JobStatusOut(found=True, status_code=code, status_label=LABELS.get(code, code or "unknown"),
                            terminal=code in ("F", "A", "X"), failed=code in ("A", "X"))
```

`src/sage/tasks/rc_notes_download.py`:
```python
from pydantic import BaseModel

from sage.sap.requirements import FmAuthorized, FmExists
from sage.tasks.base import Task

GUIDE = ("Create ZFM_RC_NOTES_DOWNLOAD (class plus remote-enabled function module) as in the attached source. "
         "It wraps CL_SCWN_DARK_API=>SCHEDULE_DOWNLOAD and only downloads notes; implementing a note stays manual in SNOTE.")


class NotesDownloadIn(BaseModel):
    notes: list[str]


class NotesDownloadOut(BaseModel):
    schedule_id: str = ""
    run_id: str = ""
    job_count: str = ""
    messages: list[str] = []


class NotesDownload(Task):
    name, Input, Output, idempotent = "rc.notes_download", NotesDownloadIn, NotesDownloadOut, False
    requirements = (FmExists("ZFM_RC_NOTES_DOWNLOAD", guide=GUIDE, source="ZFM_RC_NOTES_DOWNLOAD.txt"),
                    FmAuthorized("ZFM_RC_NOTES_DOWNLOAD", group="ZFG_MCPARCHPH"))

    async def run(self, ctx, data):
        # Unverified: row shape of IT_NOTES (type CWB_T_NOTE). Check in SE11 and adjust the key if it is not NUMM.
        res = await ctx.rfc.call(ctx.system_id, "ZFM_RC_NOTES_DOWNLOAD", IT_NOTES=[{"NUMM": n.rjust(10, "0")} for n in data.notes])
        msgs = [str(r.get("MESSAGE", "")) for r in res.get("ET_RETURN", [])]
        return NotesDownloadOut(schedule_id=str(res.get("EV_SCHEDULE_ID", "")), run_id=str(res.get("EV_RUN_ID", "")),
                                job_count=str(res.get("EV_JOB_COUNT", "")), messages=msgs)
```

`src/sage/tasks/rc_start_analysis.py`:
```python
from pydantic import BaseModel

from sage.sap.requirements import FmAuthorized, FmExists
from sage.tasks.base import Task

GUIDE = ("Create ZFM_RC_START_ANALYSIS in SE37 (function group ZFG_MCPARCHPH, remote-enabled) as in the attached source. "
         "JOB_OPEN, JOB_SUBMIT and JOB_CLOSE are not remote-enabled, so this wrapper runs them inside SAP. "
         "The RFC user's role also needs S_BTCH_JOB (JOBACTION = RELE).")


class StartAnalysisIn(BaseModel):
    job_name: str
    variant: str


class StartAnalysisOut(BaseModel):
    job_name: str
    job_count: str


class StartAnalysis(Task):
    name, Input, Output, idempotent = "rc.start_analysis", StartAnalysisIn, StartAnalysisOut, False
    requirements = (FmExists("ZFM_RC_START_ANALYSIS", guide=GUIDE, source="ZFM_RC_START_ANALYSIS.txt"),
                    FmAuthorized("ZFM_RC_START_ANALYSIS", group="ZFG_MCPARCHPH"))

    async def run(self, ctx, data):
        res = await ctx.rfc.call(ctx.system_id, "ZFM_RC_START_ANALYSIS", JOBNAME=data.job_name, VARIANT=data.variant)
        return StartAnalysisOut(job_name=str(res["REAL_JOBNAME"]).strip(), job_count=str(res["JOBCOUNT"]).strip())
```

`src/sage/tasks/rc_fetch_archive.py`:
```python
import re

from pydantic import BaseModel

from sage.sap.requirements import FmAuthorized, FmExists
from sage.tasks.base import Task

GUIDE = ("Create ZFM_RC_FETCH_ANALYSIS in SE37 (function group ZFG_MCPARCHPH, remote-enabled). The attached source says which "
         "internal call builds the ZIP and must be confirmed in a debugger on this system. Not verified on a live system.")


class FetchArchiveIn(BaseModel):
    job_name: str
    job_count: str


class FetchArchiveOut(BaseModel):
    file_path: str
    filename: str
    size_bytes: int


class FetchArchive(Task):
    name, Input, Output = "rc.fetch_archive", FetchArchiveIn, FetchArchiveOut
    requirements = (FmExists("ZFM_RC_FETCH_ANALYSIS", guide=GUIDE, source="ZFM_RC_FETCH_ANALYSIS.txt"),
                    FmAuthorized("ZFM_RC_FETCH_ANALYSIS", group="ZFG_MCPARCHPH"))

    async def run(self, ctx, data):
        res = await ctx.rfc.call(ctx.system_id, "ZFM_RC_FETCH_ANALYSIS", JOBNAME=data.job_name, JOBCOUNT=data.job_count)
        name = re.sub(r"[^A-Za-z0-9._-]", "_", str(res["FILENAME"])) or "readiness.zip"
        folder = ctx.data_dir / "downloads" / (ctx.system_label or str(ctx.system_id))
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{data.job_name}-{data.job_count}-{name}"
        blob = bytes(res["ZIP_DATA"])
        path.write_bytes(blob)
        return FetchArchiveOut(file_path=str(path), filename=name, size_bytes=len(blob))
```

- [ ] **Step 4: Implement the workflow** — `src/sage/workflows/sap_readiness_check.py`:
```python
"""SAP Readiness Check: check notes, schedule RC_COLLECT_ANALYSIS_DATA, wait for the job, download the ZIP.
Durable: one long-held run that survives restarts. Uploading the ZIP to SAP is manual."""
from pydantic import BaseModel

from sage.runtime.errors import WaitTimeout, WorkflowFailed
from sage.sap.requirements import SettingPresent, TableReadable
from sage.tasks.base import Task  # noqa: F401
from sage.tasks.rc_fetch_archive import FetchArchive, FetchArchiveIn
from sage.tasks.rc_notes_download import NotesDownload, NotesDownloadIn
from sage.tasks.rc_start_analysis import StartAnalysis, StartAnalysisIn
from sage.tasks.sap_job_status import JobStatus, JobStatusIn
from sage.tasks.sap_read_table import ReadTable, ReadTableIn
from sage.workflows.base import SettingSpec, SystemInput, Workflow

PROGRAM = "RC_COLLECT_ANALYSIS_DATA"
pad = lambda n: n.rjust(10, "0")  # noqa: E731


class ReadinessInput(SystemInput):
    variant_name: str | None = None
    job_name: str | None = None


class NoteState(BaseModel):
    number: str
    conditional: bool = False
    present: bool = False
    implemented: bool | None = None


class ReadinessOutput(BaseModel):
    job_name: str
    job_count: str
    final_status: str
    file_path: str
    filename: str
    size_bytes: int
    notes: list[NoteState]


def _in_list(field, numbers):
    return " OR ".join(f"{field} = '{pad(n)}'" for n in numbers)


class SapReadinessCheck(Workflow):
    name = "sap_readiness_check"
    description = ("Run SAP Readiness Check data collection on a registered SAP system: verify prerequisite SAP Notes "
                   "(downloading missing ones), schedule RC_COLLECT_ANALYSIS_DATA, wait until the job finishes (can take hours), "
                   "and download the ZIP archive. Upload to SAP Readiness Check stays manual.")
    Input, Output, durable = ReadinessInput, ReadinessOutput, True
    tasks = (ReadTable, NotesDownload, StartAnalysis, JobStatus, FetchArchive)
    extra_requirements = (
        TableReadable("CWBNTHEAD", guide="Allow reading CWBNTHEAD (SAP Notes header) for the RFC user."),
        TableReadable("CWBNTCUST", guide="Allow reading CWBNTCUST (note implementation status). Its field PRSTATUS is unverified; check in SE16."),
        TableReadable("VARID", guide="Allow reading VARID (report variants)."),
        SettingPresent("default_variant", level="warn",
                       guide="Create a variant for RC_COLLECT_ANALYSIS_DATA in SA38 and enter its name as the default variant here."),
    )
    binding_settings = (SettingSpec(key="default_variant", label="Default variant",
                                    description="Used when the user gives no variant. Must exist for RC_COLLECT_ANALYSIS_DATA."),)

    async def run(self, ctx, data: ReadinessInput) -> ReadinessOutput:
        cfg = await ctx.snapshot("notes_config", lambda: ctx.task_ctx.settings.get("readiness.prerequisite_notes"))
        variant = data.variant_name or ctx.task_ctx.binding.get("default_variant")
        if not variant:
            raise WorkflowFailed("No variant given and no default variant is set up for this system.")
        notes = cfg["notes"]
        required = [n["number"] for n in notes if not n.get("conditional")]
        all_numbers = [n["number"] for n in notes]

        async def present_numbers():
            r = await ctx.task(ReadTable, ReadTableIn(table="CWBNTHEAD", fields=["NUMM"], where=_in_list("NUMM", all_numbers)))
            return r

        head = await present_numbers()
        have = {row["NUMM"].lstrip("0") for row in head.rows}
        missing = [n for n in required if n not in have]
        if missing:
            await ctx.task(NotesDownload, NotesDownloadIn(notes=missing))
            poll = int(cfg["download_poll_seconds"])
            try:
                head = await ctx.wait(
                    ReadTable, ReadTableIn(table="CWBNTHEAD", fields=["NUMM"], where=_in_list("NUMM", all_numbers)),
                    until=lambda o: all(n in {r["NUMM"].lstrip("0") for r in o.rows} for n in missing),
                    backoff=[[10 ** 9, poll]], max_wait=int(cfg["download_wait_seconds"]))
            except WaitTimeout:
                raise WorkflowFailed("Required SAP Notes still missing after waiting for the download: " + ", ".join(missing))
            have = {row["NUMM"].lstrip("0") for row in head.rows}
        impl = cfg["implementation_status"]
        status = {}
        if cfg.get("require_implemented"):
            r = await ctx.task(ReadTable, ReadTableIn(table=impl["table"], fields=["NUMM", impl["field"]],
                                                      where=_in_list("NUMM", required)))
            status = {row["NUMM"].lstrip("0"): row[impl["field"]] for row in r.rows}
            not_impl = [n for n in required if status.get(n) is not None and status[n] not in impl["implemented_values"]]
            if not_impl:
                raise WorkflowFailed("Required SAP Notes downloaded but not implemented (SNOTE): " + ", ".join(not_impl))
        states = [NoteState(number=n["number"], conditional=bool(n.get("conditional")), present=n["number"] in have,
                            implemented=(status[n["number"]] in impl["implemented_values"]) if n["number"] in status else None)
                  for n in notes]

        v = await ctx.task(ReadTable, ReadTableIn(table="VARID", fields=["VARIANT"],
                                                  where=f"REPORT = '{PROGRAM}' AND VARIANT = '{variant}'"))
        if not v.rows:
            raise WorkflowFailed(f"Report variant '{variant}' does not exist for {PROGRAM} on this system.")

        job = await ctx.task(StartAnalysis, StartAnalysisIn(job_name=data.job_name or PROGRAM, variant=variant))
        final = await ctx.wait(JobStatus, JobStatusIn(job_name=job.job_name, job_count=job.job_count), until=lambda o: (not o.found) or o.terminal)
        if not final.found:
            raise WorkflowFailed(f"Job {job.job_name}/{job.job_count} was not found on the system.")
        if final.failed:
            raise WorkflowFailed(f"Job {job.job_name}/{job.job_count} ended {final.status_label}. Check SM37 on the system.")
        arch = await ctx.task(FetchArchive, FetchArchiveIn(job_name=job.job_name, job_count=job.job_count))
        return ReadinessOutput(job_name=job.job_name, job_count=job.job_count, final_status=final.status_label,
                               file_path=arch.file_path, filename=arch.filename, size_bytes=arch.size_bytes, notes=states)
```

Note on determinism: the notes branches (`missing`) depend on live SAP reads, but those reads are stored steps, so replays take the same branch. The `present_numbers` helper and the `if missing` branch both call `ctx.task`/`ctx.wait` in the same order on replay.

- [ ] **Step 5: Run to verify it passes** — `uv run pytest tests/test_readiness.py -q` — Expected: `6 passed`. If the `until` lambda for `wait` mis-handles the `download_wait_seconds` test, check that `backoff=[[10 ** 9, poll]]` yields `poll` seconds between polls and that the wait gives up after `download_wait_seconds`.

---

### Task 9: Providers (Claude and GPT)

**Files:**
- Create: `sage_api/src/sage/providers/{__init__.py,base.py,anthropic_provider.py,openai_provider.py,registry.py}`, `tests/test_providers.py`

**Interfaces:**
- Produces: events `TextDelta(text)`, `ToolUse(id, name, input)`, `Done(input_tokens, output_tokens)`; `ToolSpec(name, description, schema)`; `Provider.stream(*, model, system, messages, tools, api_key, max_tokens) -> AsyncIterator[event]`. Neutral message format (stored in `messages.content` as JSON): a list of blocks `{"type":"text","text"}`, `{"type":"tool_use","id","name","input"}`, `{"type":"tool_result","tool_use_id","content","is_error"}`. `to_openai_messages(system, messages) -> list[dict]`, `accumulate_tool_calls(deltas) -> list[ToolUse]`, `default_providers() -> dict[str, Provider]`.

- [ ] **Step 1: Write the failing tests** — `tests/test_providers.py`:
```python
from sage.providers.openai_provider import accumulate_tool_calls, to_openai_messages

NEUTRAL = [
    {"role": "user", "content": [{"type": "text", "text": "check TS3"}]},
    {"role": "assistant", "content": [{"type": "text", "text": "ok"},
                                      {"type": "tool_use", "id": "c1", "name": "wf", "input": {"system_name": "TS3"}}]},
    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "{\"a\":1}", "is_error": False}]},
]


def test_neutral_to_openai():
    out = to_openai_messages("sys", NEUTRAL)
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[1] == {"role": "user", "content": "check TS3"}
    a = out[2]
    assert a["role"] == "assistant" and a["content"] == "ok"
    assert a["tool_calls"][0] == {"id": "c1", "type": "function", "function": {"name": "wf", "arguments": "{\"system_name\": \"TS3\"}"}}
    assert out[3] == {"role": "tool", "tool_call_id": "c1", "content": "{\"a\":1}"}


def test_accumulate_streamed_tool_call_arguments():
    deltas = [
        {"index": 0, "id": "c1", "name": "wf", "arguments": "{\"system"},
        {"index": 0, "id": None, "name": None, "arguments": "_name\": \"TS3\"}"},
        {"index": 1, "id": "c2", "name": "other", "arguments": "{}"},
    ]
    uses = accumulate_tool_calls(deltas)
    assert [(u.id, u.name, u.input) for u in uses] == [("c1", "wf", {"system_name": "TS3"}), ("c2", "other", {})]
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_providers.py -q` — FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/sage/providers/__init__.py`: empty. `src/sage/providers/base.py`:
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolUse:
    id: str
    name: str
    input: dict


@dataclass
class Done:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict


class Provider(ABC):
    name: str

    @abstractmethod
    def stream(self, *, model: str, system: str, messages: list[dict], tools: list[ToolSpec],
               api_key: str, max_tokens: int) -> AsyncIterator: ...
```

`src/sage/providers/anthropic_provider.py`:
```python
"""Claude. The neutral message format is already Anthropic-shaped, so messages pass through.
Network path not run in this repo's tests (needs an API key)."""
import anthropic

from sage.providers.base import Done, Provider, TextDelta, ToolSpec, ToolUse


class AnthropicProvider(Provider):
    name = "anthropic"

    async def stream(self, *, model, system, messages, tools: list[ToolSpec], api_key, max_tokens):
        client = anthropic.AsyncAnthropic(api_key=api_key)
        kwargs = {"model": model, "max_tokens": max_tokens, "system": system, "messages": messages}
        if tools:
            kwargs["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.schema} for t in tools]
        async with client.messages.stream(**kwargs) as s:
            async for text in s.text_stream:
                yield TextDelta(text)
            final = await s.get_final_message()
        for b in final.content:
            if b.type == "tool_use":
                yield ToolUse(id=b.id, name=b.name, input=dict(b.input))
        yield Done(final.usage.input_tokens, final.usage.output_tokens)
```

`src/sage/providers/openai_provider.py`:
```python
"""GPT via Chat Completions with tools. Network path not run in this repo's tests (needs an API key)."""
import json

from openai import AsyncOpenAI

from sage.providers.base import Done, Provider, TextDelta, ToolSpec, ToolUse


def to_openai_messages(system: str, messages: list[dict]) -> list[dict]:
    out = [{"role": "system", "content": system}]
    for m in messages:
        blocks = m["content"]
        if m["role"] == "user":
            for b in blocks:
                if b["type"] == "tool_result":
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]})
            text = "".join(b["text"] for b in blocks if b["type"] == "text")
            if text:
                out.append({"role": "user", "content": text})
        else:
            msg = {"role": "assistant", "content": "".join(b["text"] for b in blocks if b["type"] == "text") or None}
            calls = [{"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b["input"])}}
                     for b in blocks if b["type"] == "tool_use"]
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
    return out


def accumulate_tool_calls(deltas: list[dict]) -> list[ToolUse]:
    acc: dict[int, dict] = {}
    for d in deltas:
        slot = acc.setdefault(d["index"], {"id": "", "name": "", "args": ""})
        slot["id"] = d.get("id") or slot["id"]
        slot["name"] = d.get("name") or slot["name"]
        slot["args"] += d.get("arguments") or ""
    return [ToolUse(id=s["id"], name=s["name"], input=json.loads(s["args"] or "{}")) for _, s in sorted(acc.items())]


class OpenAIProvider(Provider):
    name = "openai"

    async def stream(self, *, model, system, messages, tools: list[ToolSpec], api_key, max_tokens):
        client = AsyncOpenAI(api_key=api_key)
        kwargs = {"model": model, "messages": to_openai_messages(system, messages), "stream": True,
                  "stream_options": {"include_usage": True}}
        if tools:
            kwargs["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.schema}}
                               for t in tools]
        deltas, usage = [], None
        async for chunk in await client.chat.completions.create(**kwargs):
            if chunk.usage:
                usage = chunk.usage
            for choice in chunk.choices:
                if choice.delta.content:
                    yield TextDelta(choice.delta.content)
                for tc in choice.delta.tool_calls or []:
                    deltas.append({"index": tc.index, "id": tc.id, "name": tc.function.name if tc.function else None,
                                   "arguments": tc.function.arguments if tc.function else None})
        for use in accumulate_tool_calls(deltas):
            yield use
        yield Done(usage.prompt_tokens if usage else 0, usage.completion_tokens if usage else 0)
```

`src/sage/providers/registry.py`:
```python
from sage.providers.anthropic_provider import AnthropicProvider
from sage.providers.base import Provider
from sage.providers.openai_provider import OpenAIProvider


def default_providers() -> dict[str, Provider]:
    return {"anthropic": AnthropicProvider(), "openai": OpenAIProvider()}
```

- [ ] **Step 4: Run to verify it passes** — `uv run pytest tests/test_providers.py -q` — Expected: `2 passed`.

---

### Task 10: Usage, agent loop, durable resume, chats and runs routes

**Files:**
- Create: `sage_api/src/sage/{usage.py,runtime/agent.py}`, `src/sage/routes/chat_routes.py`, `tests/test_agent.py`
- Modify: `src/sage/services.py`, `src/sage/app.py`

**Interfaces:**
- Consumes: everything above. `Provider`, `WorkflowContext`, `WorkflowSetupService.authorize_run`, `UsageService`.
- Produces: `UsageService(db, clock)` with `record_run(run_id)`, `me(user_id)`, `all()`. `AgentService(*, db, audit, settings, providers, workflows, setup, rfc, data_dir, usage, clock=utcnow, poll_seconds=5)` with `create_run(chat_id, user, text) -> int`, `launch(run_id)`, `drive(run_id)`, `cancel(run_id, actor)`, `recover_on_startup()`, `start_scheduler()`, `stop_scheduler()`, `tool_specs() -> list[ToolSpec]`. `services.agent`, `services.usage`.
- Routes (login required; users reach only their own chats): `GET /api/chats`, `POST /api/chats {title?, provider, model}`, `PATCH /api/chats/{id} {provider?, model?, title?}`, `DELETE /api/chats/{id}` (soft), `GET /api/chats/{id}/messages`, `POST /api/chats/{id}/runs {text}` → `{run_id}`, `GET /api/runs/{id}/events?after=N` (SSE; each event `id: <event id>`, `data: {"type","data"}`), `POST /api/runs/{id}/cancel`, `GET /api/providers` (enabled provider and model list).

- [ ] **Step 1: Write the failing tests** — `tests/test_agent.py`:
```python
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import BaseModel

from sage.providers.base import Done, Provider, TextDelta, ToolUse
from sage.runtime.context import WorkflowContext  # noqa: F401
from sage.tasks.base import Task
from sage.workflows.base import SystemInput, Workflow
from tests.conftest import login_admin


class Out(BaseModel):
    answer: str


class PollOut(BaseModel):
    n: int


class Polls(BaseModel):
    pass


COUNT = {"polls": 0}


class PollTask(Task):
    name, Input, Output = "t.poll", Polls, PollOut

    async def run(self, ctx, data):
        COUNT["polls"] += 1
        return PollOut(n=COUNT["polls"])


class SlowWf(Workflow):
    name, description, Input, Output, durable = "slow_wf", "waits for 3 polls", SystemInput, Out, True
    tasks = (PollTask,)

    async def run(self, ctx, data):
        r = await ctx.wait(PollTask, Polls(), until=lambda o: o.n >= 3)
        return Out(answer=f"done after {r.n}")


class QuickWf(Workflow):
    name, description, Input, Output = "quick_wf", "instant", SystemInput, Out

    async def run(self, ctx, data):
        return Out(answer="quick-ok")


class Script(Provider):
    """Scripted provider: each call plays the next turn."""
    name = "anthropic"

    def __init__(self, turns):
        self.turns, self.calls = list(turns), []

    async def stream(self, *, model, system, messages, tools, api_key, max_tokens):
        self.calls.append((messages, [t.name for t in tools]))
        for ev in self.turns.pop(0):
            yield ev


class Clock:
    def __init__(self):
        self.t = datetime(2026, 6, 1, tzinfo=timezone.utc)

    def __call__(self):
        return self.t


@pytest.fixture
def script():
    return Script([])


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def app_kwargs(script, clock):
    return {"workflows": {"slow_wf": SlowWf, "quick_wf": QuickWf}, "providers": {"anthropic": script}, "clock": clock}


async def setup_world(client, app, fake_rfc, workflows=("quick_wf",)):
    await login_admin(client)
    await client.post("/api/systems", json={"label": "TS3", "sid": "TS3", "ashost": "h", "sysnr": "00", "client": "100",
                                            "rfc_user": "U", "rfc_password": "pw-secret-1"})
    for w in workflows:
        await client.put(f"/api/workflows/{w}/systems/1", json={"settings": {}})
        assert (await client.post(f"/api/workflows/{w}/systems/1/enable")).status_code == 200
    await app.state.services.settings.set("providers.anthropic_api_key", "k", "t")
    return (await client.post("/api/chats", json={"title": "t", "provider": "anthropic", "model": "claude-sonnet-5-5"})).json()["id"]


async def run_to_end(client, app, chat_id, text="go"):
    run_id = (await client.post(f"/api/chats/{chat_id}/runs", json={"text": text})).json()["run_id"]
    await app.state.services.agent.drive(run_id)
    return run_id


async def status(app, run_id):
    return (await app.state.services.db.fetchone("SELECT * FROM runs WHERE id=?", (run_id,)))


async def test_tool_call_loop_persists_and_counts(client, app, script, fake_rfc):
    cid = await setup_world(client, app, fake_rfc)
    script.turns = [[TextDelta("checking"), ToolUse("c1", "quick_wf", {"system_name": "TS3"}), Done(10, 5)],
                    [TextDelta("all good"), Done(20, 7)]]
    run_id = await run_to_end(client, app, cid)
    r = await status(app, run_id)
    assert r["status"] == "done" and r["tokens_in"] == 30 and r["tokens_out"] == 12
    msgs = (await client.get(f"/api/chats/{cid}/messages")).json()
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert json.loads(msgs[2]["content"])[0]["content"].count("quick-ok") == 1
    assert script.calls[0][1] == ["quick_wf"]                        # model sees only enabled workflows, not tasks
    u = (await client.get("/api/usage/me")).json()
    assert u[0]["requests"] == 1 and u[0]["workflow_calls"] == 1 and u[0]["tokens_in"] == 30
    ev = (await app.state.services.db.fetchall("SELECT type FROM run_events WHERE run_id=?", (run_id,)))
    assert "tool_start" in {e["type"] for e in ev} and ev[-1]["type"] == "done"


async def test_workflow_not_enabled_is_refused_to_model(client, app, script, fake_rfc):
    cid = await setup_world(client, app, fake_rfc, workflows=())
    script.turns = [[ToolUse("c1", "quick_wf", {"system_name": "TS3"}), Done(1, 1)], [TextDelta("sorry"), Done(1, 1)]]
    run_id = await run_to_end(client, app, cid)
    msgs = (await client.get(f"/api/chats/{cid}/messages")).json()
    result = json.loads(msgs[2]["content"])[0]
    assert result["is_error"] is True and "not enabled" in result["content"]
    assert (await status(app, run_id))["status"] == "done"


async def test_max_turns_cap(client, app, script, fake_rfc):
    cid = await setup_world(client, app, fake_rfc)
    await app.state.services.settings.set("agent.max_turns", 2, "t")
    loop = [ToolUse("c%d" % i, "quick_wf", {"system_name": "TS3"}) for i in range(5)]
    script.turns = [[loop[i], Done(1, 1)] for i in range(5)]
    run_id = await run_to_end(client, app, cid)
    r = await status(app, run_id)
    assert r["status"] == "failed" and "max_turns" in r["error"]


async def test_chat_delete_keeps_records(client, app, script, fake_rfc):
    cid = await setup_world(client, app, fake_rfc)
    script.turns = [[ToolUse("c1", "quick_wf", {"system_name": "TS3"}), Done(1, 1)], [TextDelta("x"), Done(1, 1)]]
    run_id = await run_to_end(client, app, cid)
    assert (await client.delete(f"/api/chats/{cid}")).status_code == 200
    assert (await client.get("/api/chats")).json() == []
    db = app.state.services.db
    assert (await db.fetchone("SELECT COUNT(*) c FROM runs WHERE id=?", (run_id,)))["c"] == 1
    assert (await db.fetchone("SELECT COUNT(*) c FROM tool_calls WHERE run_id=?", (run_id,)))["c"] == 1
    assert (await db.fetchone("SELECT COUNT(*) c FROM audit_log WHERE event='chat.delete'"))["c"] == 1
    assert (await client.post(f"/api/chats/{cid}/runs", json={"text": "again"})).status_code == 404


async def test_durable_run_waits_survives_restart_and_completes(client, app, script, fake_rfc, clock):
    COUNT["polls"] = 0
    cid = await setup_world(client, app, fake_rfc, workflows=("slow_wf",))
    script.turns = [[ToolUse("c1", "slow_wf", {"system_name": "TS3"}), Done(1, 1)], [TextDelta("finished"), Done(1, 1)]]
    run_id = await run_to_end(client, app, cid)
    r = await status(app, run_id)
    assert r["status"] == "waiting" and r["resume_at"]
    agent = app.state.services.agent
    for _ in range(5):                                                # simulate restart + scheduler wake-ups
        r = await status(app, run_id)
        if r["status"] != "waiting":
            break
        clock.t = datetime.fromisoformat(r["resume_at"])
        await agent.recover_on_startup()
        await agent.drive(run_id)
    r = await status(app, run_id)
    assert r["status"] == "done" and COUNT["polls"] == 3
    msgs = (await client.get(f"/api/chats/{cid}/messages")).json()
    assert "done after 3" in json.loads(msgs[2]["content"])[0]["content"]


async def test_cancel_waiting_run(client, app, script, fake_rfc):
    COUNT["polls"] = 0
    cid = await setup_world(client, app, fake_rfc, workflows=("slow_wf",))
    script.turns = [[ToolUse("c1", "slow_wf", {"system_name": "TS3"}), Done(1, 1)]]
    run_id = await run_to_end(client, app, cid)
    assert (await client.post(f"/api/runs/{run_id}/cancel")).status_code == 200
    assert (await status(app, run_id))["status"] == "cancelled"
    tc = await app.state.services.db.fetchone("SELECT status FROM tool_calls WHERE run_id=?", (run_id,))
    assert tc["status"] == "cancelled"


async def test_non_durable_running_run_fails_on_startup_recovery(client, app, script, fake_rfc):
    cid = await setup_world(client, app, fake_rfc)
    db = app.state.services.db
    await db.execute("INSERT INTO runs(id,chat_id,user_id,provider,model,status,started_at) VALUES(99,?,1,'anthropic','m','running','t')", (cid,))
    await app.state.services.agent.recover_on_startup()
    r = await status(app, 99)
    assert r["status"] == "failed" and "restart" in r["error"]


async def test_users_cannot_touch_other_users_chats(client, app, script, fake_rfc):
    cid = await setup_world(client, app, fake_rfc)
    await client.post("/api/users", json={"username": "bob", "password": "bob-password-1", "role": "user"})
    await client.post("/api/auth/logout")
    await client.post("/api/auth/login", json={"username": "bob", "password": "bob-password-1"})
    assert (await client.get(f"/api/chats/{cid}/messages")).status_code == 404
    assert (await client.post(f"/api/chats/{cid}/runs", json={"text": "x"})).status_code == 404
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_agent.py -q` — FAIL (no `/api/chats`).

- [ ] **Step 3: Implement usage** — `src/sage/usage.py`:
```python
"""Usage counts only; there are no limits."""
from sage.util import utcnow


class UsageService:
    def __init__(self, db, clock=utcnow):
        self._db, self._clock = db, clock

    async def record_run(self, run_id: int):
        run = await self._db.fetchone("SELECT * FROM runs WHERE id=?", (run_id,))
        wf = (await self._db.fetchone("SELECT COUNT(*) c FROM tool_calls WHERE run_id=?", (run_id,)))["c"]
        tasks = (await self._db.fetchone(
            "SELECT COUNT(*) c FROM tool_steps s JOIN tool_calls t ON t.id=s.tool_call_id "
            "WHERE t.run_id=? AND s.kind IN ('task','poll')", (run_id,)))["c"]
        day = self._clock().date().isoformat()
        await self._db.execute(
            "INSERT INTO usage_counters(user_id,day,requests,tokens_in,tokens_out,workflow_calls,task_calls) VALUES(?,?,1,?,?,?,?) "
            "ON CONFLICT(user_id,day) DO UPDATE SET requests=requests+1, tokens_in=tokens_in+excluded.tokens_in, "
            "tokens_out=tokens_out+excluded.tokens_out, workflow_calls=workflow_calls+excluded.workflow_calls, "
            "task_calls=task_calls+excluded.task_calls",
            (run["user_id"], day, run["tokens_in"], run["tokens_out"], wf, tasks))

    async def me(self, user_id: int) -> list[dict]:
        return await self._db.fetchall("SELECT * FROM usage_counters WHERE user_id=? ORDER BY day DESC", (user_id,))

    async def all(self) -> list[dict]:
        return await self._db.fetchall(
            "SELECT u.username, c.* FROM usage_counters c JOIN users u ON u.id=c.user_id ORDER BY c.day DESC, u.username")
```

- [ ] **Step 4: Implement the agent** — `src/sage/runtime/agent.py`:
```python
"""Agent loop. Messages and tool calls are stored, so a run can be rebuilt after a restart.
A durable workflow that is waiting leaves the run in status 'waiting' with resume_at; the scheduler resumes it."""
import asyncio
import json
import logging

from pydantic import ValidationError

from sage.providers.base import Done, TextDelta, ToolSpec, ToolUse
from sage.runtime.context import WorkflowContext
from sage.runtime.errors import RunCancelled, WorkflowFailed, WorkflowSuspended
from sage.tasks.base import TaskContext
from sage.util import iso, parse_iso, utcnow
from sage.workflow_setup import AccessError

log = logging.getLogger("sage.agent")

SYSTEM_PROMPT = ("You are DXC Sage, an assistant for SAP work. Use the provided workflow tools when they fit. "
                 "A workflow can run for hours; its result arrives when it finishes. Never invent results.")


class AgentService:
    def __init__(self, *, db, audit, settings, providers, workflows, setup, rfc, data_dir, usage, clock=utcnow, poll_seconds=5):
        self._db, self._audit, self._settings, self._providers = db, audit, settings, providers
        self._workflows, self._setup, self._rfc, self._data_dir, self._usage = workflows, setup, rfc, data_dir, usage
        self._clock, self._poll = clock, poll_seconds
        self._tasks: dict[int, asyncio.Task] = {}
        self._scheduler: asyncio.Task | None = None

    # ---- runs ----
    async def _run(self, run_id):
        return await self._db.fetchone("SELECT * FROM runs WHERE id=?", (run_id,))

    async def _emit(self, run_id, type_, data=None):
        await self._db.execute("INSERT INTO run_events(run_id,type,data,created_at) VALUES(?,?,?,?)",
                               (run_id, type_, json.dumps(data or {}, default=str), iso(self._clock())))

    async def create_run(self, chat_id, user, text) -> int:
        chat = await self._db.fetchone("SELECT * FROM chats WHERE id=? AND user_id=? AND deleted_at IS NULL", (chat_id, user["id"]))
        if not chat:
            raise LookupError("chat")
        if await self._db.fetchone("SELECT id FROM runs WHERE chat_id=? AND status IN ('running','waiting')", (chat_id,)):
            raise RuntimeError("This chat already has an active run.")
        now = iso(self._clock())
        async with self._db.tx() as t:
            run_id = await t.execute("INSERT INTO runs(chat_id,user_id,provider,model,status,started_at) VALUES(?,?,?,?,'running',?)",
                                     (chat_id, user["id"], chat["provider"], chat["model"], now))
            await t.execute("INSERT INTO messages(chat_id,run_id,role,content,created_at) VALUES(?,?,'user',?,?)",
                            (chat_id, run_id, json.dumps([{"type": "text", "text": text}]), now))
        await self._audit.write("run.start", user["username"], run_id, {"chat_id": chat_id, "provider": chat["provider"], "model": chat["model"]})
        return run_id

    def launch(self, run_id):
        if run_id in self._tasks:
            return
        task = asyncio.create_task(self.drive(run_id))
        self._tasks[run_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(run_id, None))

    async def drive(self, run_id):
        run = await self._run(run_id)
        if run["status"] not in ("running", "waiting"):
            return
        await self._db.execute("UPDATE runs SET status='running', resume_at=NULL WHERE id=?", (run_id,))
        try:
            await self._loop(run_id)
        except WorkflowSuspended:
            return
        except RunCancelled:
            await self._finish(run_id, "cancelled")
        except Exception as e:  # noqa: BLE001
            log.exception("run %s failed", run_id)
            await self._finish(run_id, "failed", str(e))

    async def _finish(self, run_id, status, error=None):
        await self._db.execute("UPDATE runs SET status=?, error=?, ended_at=?, resume_at=NULL WHERE id=?",
                               (status, error, iso(self._clock()), run_id))
        run = await self._run(run_id)
        await self._usage.record_run(run_id)
        await self._audit.write("run.end", "system", run_id, {"status": status, "error": error,
                                                              "tokens_in": run["tokens_in"], "tokens_out": run["tokens_out"]})
        await self._emit(run_id, {"done": "done", "failed": "error", "cancelled": "cancelled"}[status], {"error": error})

    async def cancel(self, run_id, actor):
        run = await self._run(run_id)
        await self._db.execute("UPDATE runs SET cancel_requested=1 WHERE id=?", (run_id,))
        await self._audit.write("run.cancel", actor, run_id)
        if run["status"] == "waiting" and run_id not in self._tasks:
            await self._db.execute("UPDATE tool_calls SET status='cancelled', ended_at=? WHERE run_id=? AND status IN ('waiting','running')",
                                   (iso(self._clock()), run_id))
            await self._finish(run_id, "cancelled")

    async def _check_cancel(self, run_id):
        if (await self._run(run_id))["cancel_requested"]:
            raise RunCancelled()

    # ---- loop ----
    async def _history(self, chat_id):
        rows = await self._db.fetchall("SELECT role,content FROM messages WHERE chat_id=? ORDER BY id", (chat_id,))
        return [{"role": r["role"], "content": json.loads(r["content"])} for r in rows]

    async def _add_message(self, run, role, blocks):
        await self._db.execute("INSERT INTO messages(chat_id,run_id,role,content,created_at) VALUES(?,?,?,?,?)",
                               (run["chat_id"], run["id"], role, json.dumps(blocks), iso(self._clock())))

    async def tool_specs(self) -> list[ToolSpec]:
        disabled = await self._settings.get("workflows.disabled")
        specs = []
        for name, cls in self._workflows.items():
            if name in disabled:
                continue
            systems = await self._setup.enabled_systems(name)
            if not systems:
                continue
            schema = cls.Input.model_json_schema()
            if "system_name" in schema.get("properties", {}):
                schema["properties"]["system_name"]["enum"] = [s["label"] for s in systems]
            specs.append(ToolSpec(name=name, description=cls.description, schema=schema))
        return specs

    async def _loop(self, run_id):
        run = await self._run(run_id)
        user = await self._db.fetchone("SELECT * FROM users WHERE id=?", (run["user_id"],))
        provider = self._providers[run["provider"]]
        api_key = await self._settings.get(f"providers.{run['provider']}_api_key")
        if not api_key:
            raise WorkflowFailed(f"No API key is set for {run['provider']}.")
        max_turns = int(await self._settings.get("agent.max_turns"))
        turns = 0
        while True:
            await self._check_cancel(run_id)
            history = await self._history(run["chat_id"])
            last = history[-1]
            pending = [b for b in last["content"] if b["type"] == "tool_use"] if last["role"] == "assistant" else []
            if pending:
                results = await self._run_tools(run_id, user, pending)
                await self._add_message(run, "user", results)
                continue
            if last["role"] == "assistant":
                return await self._finish(run_id, "done")
            if turns >= max_turns:
                return await self._finish(run_id, "failed", "max_turns reached")
            turns += 1
            blocks = await self._ask(run_id, run, provider, api_key, history)
            await self._add_message(run, "assistant", blocks)

    async def _ask(self, run_id, run, provider, api_key, history):
        tools = await self.tool_specs()
        text, uses, tin, tout = "", [], 0, 0
        max_tokens = int(await self._settings.get("providers.max_tokens"))
        async for ev in provider.stream(model=run["model"], system=SYSTEM_PROMPT, messages=history, tools=tools,
                                        api_key=api_key, max_tokens=max_tokens):
            if isinstance(ev, TextDelta):
                text += ev.text
                await self._emit(run_id, "text", {"text": ev.text})
            elif isinstance(ev, ToolUse):
                uses.append(ev)
            elif isinstance(ev, Done):
                tin, tout = ev.input_tokens, ev.output_tokens
        await self._db.execute("UPDATE runs SET tokens_in=tokens_in+?, tokens_out=tokens_out+? WHERE id=?", (tin, tout, run_id))
        blocks = ([{"type": "text", "text": text}] if text else []) + \
                 [{"type": "tool_use", "id": u.id, "name": u.name, "input": u.input} for u in uses]
        return blocks or [{"type": "text", "text": "(no output)"}]

    async def _run_tools(self, run_id, user, uses):
        results = []
        for use in uses:
            existing = await self._db.fetchone("SELECT * FROM tool_calls WHERE run_id=? AND provider_call_id=?", (run_id, use["id"]))
            if existing and existing["status"] in ("ok", "error"):
                results.append({"type": "tool_result", "tool_use_id": use["id"], "content": existing["output"] or "",
                                "is_error": existing["status"] == "error"})
            else:
                results.append(await self._execute(run_id, user, use, existing))
        return results

    async def _execute(self, run_id, user, use, existing):
        name, actor = use["name"], user["username"]
        if existing:
            call_id = existing["id"]
        else:
            call_id = await self._db.execute(
                "INSERT INTO tool_calls(run_id,provider_call_id,workflow,input,status,started_at) VALUES(?,?,?,?,'running',?)",
                (run_id, use["id"], name, json.dumps(use["input"]), iso(self._clock())))
            await self._audit.write("tool.call", actor, run_id, {"workflow": name, "input": use["input"]})
            await self._emit(run_id, "tool_start", {"workflow": name, "input": use["input"]})
        status, output = "ok", ""
        try:
            cls = self._workflows.get(name)
            if cls is None:
                raise WorkflowFailed(f"Unknown workflow '{name}'.")
            data = cls.Input.model_validate(use["input"])
            system, binding = None, {}
            if hasattr(data, "system_name"):
                system, binding = await self._setup.authorize_run(name, data.system_name, actor)
                await self._db.execute("UPDATE tool_calls SET system_id=? WHERE id=?", (system["id"], call_id))
            backoff = await self._settings.get("wait.backoff")
            max_wait = int(await self._settings.get("wait.max_wait"))
            task_ctx = TaskContext(system["id"] if system else None, self._rfc, self._settings, binding, self._data_dir,
                                   system["label"] if system else "")

            async def cancelled():
                return bool((await self._run(run_id))["cancel_requested"])

            async def emit(t, d):
                await self._emit(run_id, t, d)

            ctx = WorkflowContext(db=self._db, audit=self._audit, run_id=run_id, tool_call_id=call_id, workflow=name, actor=actor,
                                  task_ctx=task_ctx, backoff=backoff, max_wait=max_wait, clock=self._clock,
                                  is_cancelled=cancelled, emit=emit)
            out = await cls().run(ctx, data)
            output = out.model_dump_json()
        except WorkflowSuspended as s:
            await self._db.execute("UPDATE tool_calls SET status='waiting' WHERE id=?", (call_id,))
            await self._db.execute("UPDATE runs SET status='waiting', resume_at=? WHERE id=?", (iso(s.resume_at), run_id))
            await self._emit(run_id, "waiting", {"workflow": name, "resume_at": iso(s.resume_at)})
            raise
        except RunCancelled:
            await self._db.execute("UPDATE tool_calls SET status='cancelled', ended_at=? WHERE id=?", (iso(self._clock()), call_id))
            raise
        except (WorkflowFailed, AccessError) as e:
            status, output = "error", str(e)
        except ValidationError as e:
            status, output = "error", f"Invalid input: {e.errors(include_url=False)}"
        except Exception:  # noqa: BLE001
            log.exception("workflow %s crashed", name)
            status, output = "error", "Internal error while running the workflow."
        await self._db.execute("UPDATE tool_calls SET status=?, output=?, ended_at=? WHERE id=?",
                               (status, output, iso(self._clock()), call_id))
        await self._audit.write("tool.end", actor, run_id, {"workflow": name, "status": status})
        await self._emit(run_id, "tool_end", {"workflow": name, "status": status})
        return {"type": "tool_result", "tool_use_id": use["id"], "content": output, "is_error": status != "ok"}

    # ---- restart and scheduling ----
    async def recover_on_startup(self):
        now = iso(self._clock())
        for r in await self._db.fetchall("SELECT id,status FROM runs WHERE status IN ('running','waiting')"):
            if r["id"] in self._tasks:
                continue
            call = await self._db.fetchone("SELECT workflow FROM tool_calls WHERE run_id=? AND status IN ('running','waiting')", (r["id"],))
            cls = self._workflows.get(call["workflow"]) if call else None
            if cls is not None and cls.durable:
                if r["status"] == "running":
                    await self._db.execute("UPDATE runs SET status='waiting', resume_at=? WHERE id=?", (now, r["id"]))
            elif r["status"] == "running":
                await self._db.execute("UPDATE tool_calls SET status='error', output='Interrupted by a server restart.' "
                                       "WHERE run_id=? AND status='running'", (r["id"],))
                await self._finish(r["id"], "failed", "Interrupted by a server restart.")

    async def _tick(self):
        now = iso(self._clock())
        for r in await self._db.fetchall("SELECT id FROM runs WHERE status='waiting' AND resume_at<=?", (now,)):
            self.launch(r["id"])

    def start_scheduler(self):
        async def loop():
            while True:
                try:
                    await self._tick()
                except Exception:  # noqa: BLE001
                    log.exception("scheduler tick failed")
                await asyncio.sleep(self._poll)
        self._scheduler = asyncio.create_task(loop())

    async def stop_scheduler(self):
        if self._scheduler:
            self._scheduler.cancel()
        for t in list(self._tasks.values()):
            t.cancel()
```

- [ ] **Step 5: Implement routes** — `src/sage/routes/chat_routes.py`:
```python
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from sage.deps import current_user
from sage.util import iso

router = APIRouter(prefix="/api")


class NewChat(BaseModel):
    title: str = "New chat"
    provider: str
    model: str


class ChatPatch(BaseModel):
    title: str | None = None
    provider: str | None = None
    model: str | None = None


class Text(BaseModel):
    text: str


def _svc(request):
    return request.app.state.services


async def _check_model(svc, provider, model):
    models = await svc.settings.get("providers.models")
    if provider not in models or model not in models[provider]:
        raise HTTPException(400, "model_not_allowed")
    if not await svc.settings.get(f"providers.{provider}_api_key"):
        raise HTTPException(400, "provider_not_configured")


async def _own_chat(svc, chat_id, user):
    chat = await svc.db.fetchone("SELECT * FROM chats WHERE id=? AND user_id=? AND deleted_at IS NULL", (chat_id, user["id"]))
    if not chat:
        raise HTTPException(404, "chat_not_found")
    return chat


@router.get("/providers")
async def providers(request: Request, user: dict = Depends(current_user)):
    svc = _svc(request)
    models = await svc.settings.get("providers.models")
    return {p: m for p, m in models.items() if await svc.settings.get(f"providers.{p}_api_key")}


@router.get("/chats")
async def list_chats(request: Request, user: dict = Depends(current_user)):
    return await _svc(request).db.fetchall(
        "SELECT c.id,c.title,c.provider,c.model,c.created_at,"
        "(SELECT status FROM runs r WHERE r.chat_id=c.id ORDER BY r.id DESC LIMIT 1) AS last_run_status,"
        "(SELECT id FROM runs r WHERE r.chat_id=c.id ORDER BY r.id DESC LIMIT 1) AS last_run_id "
        "FROM chats c WHERE c.user_id=? AND c.deleted_at IS NULL ORDER BY c.id DESC", (user["id"],))


@router.post("/chats")
async def create_chat(body: NewChat, request: Request, user: dict = Depends(current_user)):
    svc = _svc(request)
    await _check_model(svc, body.provider, body.model)
    cid = await svc.db.execute("INSERT INTO chats(user_id,title,provider,model,created_at) VALUES(?,?,?,?,?)",
                               (user["id"], body.title, body.provider, body.model, iso(svc.clock())))
    await svc.audit.write("chat.create", user["username"], detail={"chat_id": cid})
    return {"id": cid}


@router.patch("/chats/{chat_id}")
async def patch_chat(chat_id: int, body: ChatPatch, request: Request, user: dict = Depends(current_user)):
    svc = _svc(request)
    chat = await _own_chat(svc, chat_id, user)
    provider, model = body.provider or chat["provider"], body.model or chat["model"]
    if body.provider or body.model:
        await _check_model(svc, provider, model)
    await svc.db.execute("UPDATE chats SET title=?, provider=?, model=? WHERE id=?",
                         (body.title or chat["title"], provider, model, chat_id))
    return {"ok": True}


@router.delete("/chats/{chat_id}")
async def delete_chat(chat_id: int, request: Request, user: dict = Depends(current_user)):
    svc = _svc(request)
    await _own_chat(svc, chat_id, user)
    await svc.db.execute("UPDATE chats SET deleted_at=? WHERE id=?", (iso(svc.clock()), chat_id))
    await svc.audit.write("chat.delete", user["username"], detail={"chat_id": chat_id})
    return {"ok": True}


@router.get("/chats/{chat_id}/messages")
async def messages(chat_id: int, request: Request, user: dict = Depends(current_user)):
    svc = _svc(request)
    await _own_chat(svc, chat_id, user)
    return await svc.db.fetchall("SELECT id,run_id,role,content,created_at FROM messages WHERE chat_id=? ORDER BY id", (chat_id,))


@router.post("/chats/{chat_id}/runs")
async def start_run(chat_id: int, body: Text, request: Request, user: dict = Depends(current_user)):
    svc = _svc(request)
    try:
        run_id = await svc.agent.create_run(chat_id, user, body.text)
    except LookupError:
        raise HTTPException(404, "chat_not_found")
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    if not svc.manual_drive:
        svc.agent.launch(run_id)
    return {"run_id": run_id}


async def _own_run(svc, run_id, user):
    run = await svc.db.fetchone("SELECT * FROM runs WHERE id=?", (run_id,))
    if not run or (run["user_id"] != user["id"] and user["role"] != "admin"):
        raise HTTPException(404, "run_not_found")
    return run


@router.post("/runs/{run_id}/cancel")
async def cancel(run_id: int, request: Request, user: dict = Depends(current_user)):
    svc = _svc(request)
    await _own_run(svc, run_id, user)
    await svc.agent.cancel(run_id, user["username"])
    return {"ok": True}


@router.get("/runs/{run_id}/events")
async def events(run_id: int, request: Request, after: int = 0, user: dict = Depends(current_user)):
    svc = _svc(request)
    await _own_run(svc, run_id, user)

    async def gen():
        last, idle = after, 0
        while True:
            rows = await svc.db.fetchall("SELECT id,type,data FROM run_events WHERE run_id=? AND id>? ORDER BY id", (run_id, last))
            for r in rows:
                last, idle = r["id"], 0
                yield f"id: {r['id']}\ndata: {json.dumps({'type': r['type'], 'data': json.loads(r['data'])})}\n\n"
            run = await svc.db.fetchone("SELECT status FROM runs WHERE id=?", (run_id,))
            if not rows and run["status"] in ("done", "failed", "cancelled"):
                return
            if await request.is_disconnected():
                return
            idle += 1
            if idle % 50 == 0:
                yield ": ping\n\n"
            await asyncio.sleep(0.3)
    return StreamingResponse(gen(), media_type="text/event-stream")
```
`manual_drive`: a `services` flag that is `False` in production and set `True` by tests. Add to `create_app` a parameter-free rule: in `services.py`, `manual_drive = os.getenv("SAGE_TEST_MANUAL_DRIVE") == "1"`; and in `tests/conftest.py` `app` fixture set `monkeypatch`-style via `os.environ["SAGE_TEST_MANUAL_DRIVE"] = "1"` at the top of the fixture (use `monkeypatch.setenv`; add `monkeypatch` to the fixture arguments). Tests then call `agent.drive(run_id)` themselves.

`services.py`: add imports (`os`, `UsageService`, `AgentService`, `default_providers`) and before the `return`:
```python
    usage = UsageService(db, clock)
    agent = AgentService(db=db, audit=audit, settings=settings, providers=providers or default_providers(), workflows=wf,
                         setup=setup, rfc=rfc, data_dir=data_dir, usage=usage, clock=clock)
```
Add `usage=usage, agent=agent, manual_drive=os.getenv("SAGE_TEST_MANUAL_DRIVE") == "1"` to the namespace. In `app.py` lifespan, after the bootstrap call: `await svc.agent.recover_on_startup()`, `svc.agent.start_scheduler()`; before closing the db: `await svc.agent.stop_scheduler()`. Include `chat_routes.router`. Add a route `GET /api/usage/me` returning `await svc.usage.me(user["id"])` to `chat_routes.py` (any user):
```python
@router.get("/usage/me")
async def usage_me(request: Request, user: dict = Depends(current_user)):
    return await _svc(request).usage.me(user["id"])
```

- [ ] **Step 6: Run to verify it passes** — `uv run pytest tests/test_agent.py -q` — Expected: `8 passed`. If `test_durable_run...` loops, check that `recover_on_startup` does not flip a `waiting` run, and that `drive` sets `resume_at=NULL` only when it starts.

---

### Task 11: Admin routes (runs, audit, usage, settings) and final backend wiring

**Files:**
- Create: `sage_api/src/sage/routes/admin_routes.py`, `tests/test_admin_routes.py`
- Modify: `src/sage/app.py`

**Interfaces:**
- Routes (admin only): `GET /api/runs?user_id=&status=&limit=&offset=` (includes deleted chats; each row has `chat_deleted`), `GET /api/runs/{id}/detail` (run, tool_calls, tool_steps), `GET /api/audit?event=&actor=&limit=&offset=`, `GET /api/audit/export.csv`, `POST /api/audit/verify`, `GET /api/usage`, `GET /api/settings`, `PUT /api/settings {key,value}`. Note: `GET /api/usage/me` (Task 10) stays for every user.

- [ ] **Step 1: Write the failing tests** — `tests/test_admin_routes.py`:
```python
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
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_admin_routes.py -q` — FAIL (404 on `/api/settings`).

- [ ] **Step 3: Implement** — `src/sage/routes/admin_routes.py`:
```python
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from sage.deps import admin_user

router = APIRouter(prefix="/api")


class SettingBody(BaseModel):
    key: str
    value: object


def _svc(request):
    return request.app.state.services


@router.get("/settings")
async def get_settings(request: Request, admin: dict = Depends(admin_user)):
    return await _svc(request).settings.public()


@router.put("/settings")
async def put_setting(body: SettingBody, request: Request, admin: dict = Depends(admin_user)):
    try:
        await _svc(request).settings.set(body.key, body.value, admin["username"])
    except KeyError:
        raise HTTPException(400, "unknown_setting")
    return {"ok": True}


@router.get("/usage")
async def usage_all(request: Request, admin: dict = Depends(admin_user)):
    return await _svc(request).usage.all()


@router.get("/runs")
async def runs(request: Request, user_id: int | None = None, status: str | None = None, limit: int = 100, offset: int = 0,
               admin: dict = Depends(admin_user)):
    where, args = [], []
    if user_id is not None:
        where.append("r.user_id=?"); args.append(user_id)
    if status:
        where.append("r.status=?"); args.append(status)
    sql = ("SELECT r.*, u.username, c.title, (c.deleted_at IS NOT NULL) AS chat_deleted FROM runs r "
           "JOIN users u ON u.id=r.user_id JOIN chats c ON c.id=r.chat_id "
           + ("WHERE " + " AND ".join(where) if where else "") + " ORDER BY r.id DESC LIMIT ? OFFSET ?")
    rows = await _svc(request).db.fetchall(sql, (*args, min(limit, 500), offset))
    for r in rows:
        r["chat_deleted"] = bool(r["chat_deleted"])
    return rows


@router.get("/runs/{run_id}/detail")
async def run_detail(run_id: int, request: Request, admin: dict = Depends(admin_user)):
    db = _svc(request).db
    run = await db.fetchone("SELECT * FROM runs WHERE id=?", (run_id,))
    if not run:
        raise HTTPException(404, "run_not_found")
    calls = await db.fetchall("SELECT * FROM tool_calls WHERE run_id=? ORDER BY id", (run_id,))
    for c in calls:
        c["steps"] = await db.fetchall("SELECT * FROM tool_steps WHERE tool_call_id=? ORDER BY seq, attempt", (c["id"],))
    return {"run": run, "tool_calls": calls}


@router.get("/audit")
async def audit_list(request: Request, event: str | None = None, actor: str | None = None, limit: int = 200, offset: int = 0,
                     admin: dict = Depends(admin_user)):
    where, args = [], []
    if event:
        where.append("event=?"); args.append(event)
    if actor:
        where.append("actor=?"); args.append(actor)
    sql = "SELECT * FROM audit_log " + ("WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ? OFFSET ?"
    return await _svc(request).db.fetchall(sql, (*args, min(limit, 1000), offset))


@router.get("/audit/export.csv")
async def audit_csv(request: Request, admin: dict = Depends(admin_user)):
    rows = await _svc(request).db.fetchall("SELECT id,ts,event,actor,run_id,detail FROM audit_log ORDER BY id")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "ts", "event", "actor", "run_id", "detail"])
    for r in rows:
        w.writerow([r["id"], r["ts"], r["event"], r["actor"], r["run_id"], r["detail"]])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv")


@router.post("/audit/verify")
async def audit_verify(request: Request, admin: dict = Depends(admin_user)):
    ok, bad = await _svc(request).audit.verify()
    return {"ok": ok, "bad_id": bad}
```
`app.py`: import and include `admin_routes.router`.

Route order note: `GET /api/runs/{run_id}/events` (chat_routes) and `GET /api/runs/{run_id}/detail` do not collide.

- [ ] **Step 4: Run to verify it passes** — `uv run pytest tests/test_admin_routes.py -q` — Expected: `3 passed`.

---

### Task 12: Backend Dockerfile and finish

**Files:**
- Create: `sage_api/Dockerfile`, `sage_api/vendor/nwrfcsdk/.gitkeep`, `Applications/DXCSage/docker-compose.yml`

**Interfaces:** none (build files). Not run in this plan (Docker checks are out of the pace budget); say so in the report.

- [ ] **Step 1: Write the files**

`sage_api/Dockerfile`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml ./
COPY src ./src
# SAP NW RFC SDK and a pyrfc wheel are supplied by you in vendor/ (licensed, not in git).
COPY vendor /opt/vendor
RUN uv pip install --system --no-cache . \
 && (ls /opt/vendor/*.whl >/dev/null 2>&1 && uv pip install --system /opt/vendor/*.whl || echo "pyrfc wheel not provided: SAP calls will fail until it is added")
ENV SAPNWRFC_HOME=/opt/vendor/nwrfcsdk LD_LIBRARY_PATH=/opt/vendor/nwrfcsdk/lib SAGE_DATA_DIR=/data SAGE_KEY_DIR=/keys
EXPOSE 29700
CMD ["uvicorn", "sage.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "29700"]
```

`docker-compose.yml` (the web service is added by the frontend plan, Task 14):
```yaml
services:
  sage_api:
    build: ./sage_api
    ports: ["${SERVICE_BIND:-0.0.0.0}:29700:29700"]
    env_file: [{path: .env, required: false}]
    extra_hosts: ["host.docker.internal:host-gateway"]
    volumes: ["sage_data:/data", "sage_keys:/keys"]
    restart: unless-stopped
volumes:
  sage_data:
  sage_keys:
```

- [ ] **Step 2: Run the backend tests that cover this plan, once**

Run: `cd sage_api; uv run pytest tests/test_audit.py tests/test_settings.py tests/test_auth.py tests/test_rfc.py tests/test_systems.py tests/test_requirements.py tests/test_context.py tests/test_health_setup.py tests/test_readiness.py tests/test_providers.py tests/test_agent.py tests/test_admin_routes.py -q`
Expected: all pass (about 70 tests). This is the whole backend suite and is the one allowed full run, because it is new code; if it takes longer than 2 minutes, stop and report.

- [ ] **Step 3: Commit once** (the user wants a commit after changes; one commit for the whole plan)

```powershell
cd D:\User\Documents\Programming\Applications\DXCSage
git add .gitignore .env.example AGENTS.md CLAUDE.md docker-compose.yml sage_api docs
git commit -m "feat: DXC Sage backend (auth, systems, durable workflows, readiness check, audit)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Self-Review (spec coverage)

- Two services, one backend: Tasks 0–12 (`sage_api`), frontend in its own plan. SQLite WAL, Docker compose: Tasks 1, 12.
- Local accounts, admin/user, never deleted, bootstrap admin only in env: Task 3. DB-only settings, encrypted secrets, key in its own volume: Tasks 2, 12 (compose volume `sage_keys`).
- Providers Claude and GPT: Task 9. Agent loop, loop cap, cancel, SSE, tokens, chat soft delete, records remain: Task 10.
- Audit hash chain, append-only, scrub, verify, CSV export, filters: Tasks 1, 11. Usage counts, no limits: Tasks 10, 11.
- Workflows over shared tasks, replayable steps, `ctx.task/wait/snapshot`, auto-discovery: Tasks 6, 7, 8. Tools exposed to the model are workflows only: Task 10 `tool_specs`.
- PyRFC only, `RFC_READ_TABLE` with width split (merged by key, a deviation from the spec's positional merge, recorded in the spec edit), row cap, no joins: Task 4.
- System registry, test on save, inactive until pass, admin only, label and SID for users: Task 5.
- Health checks per system and workflow, blocked propagation, never write FMs, max age, refuse on fail: Tasks 6, 7, 10 (`authorize_run`).
- Workflow setup per system, guide with live status and combined authorization table, per-system settings (`default_variant`): Task 7.
- Durable runs: Tasks 6, 8, 10 (replay, `waiting`/`resume_at`, startup recovery, scheduler, cancel while waiting).
- Readiness check workflow (notes, variant, schedule, wait, download): Task 8.
- Not implemented, by design: write-confirmation flag, SSO, limits, email watchers, other providers.
- Known gaps to confirm on a real system (labelled in code): pyrfc connector and error mapping, `SUSR_USER_AUTH_FOR_OBJ_GET`, `CWBNTCUST/PRSTATUS`, `IT_NOTES` shape, BTCSTATUS codes, the ABAP function modules themselves.
