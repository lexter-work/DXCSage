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
CREATE TABLE IF NOT EXISTS abap_names(
  system_id INTEGER NOT NULL REFERENCES systems(id), abap_object_id TEXT NOT NULL, name TEXT NOT NULL,
  updated_by TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY(system_id, abap_object_id), UNIQUE(system_id, name));
CREATE TABLE IF NOT EXISTS workflow_systems(
  id INTEGER PRIMARY KEY, workflow TEXT NOT NULL, system_id INTEGER NOT NULL REFERENCES systems(id),
  status TEXT NOT NULL CHECK(status IN ('setup','enabled','disabled')),
  settings TEXT NOT NULL DEFAULT '{}', enabled_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(workflow, system_id));
"""
