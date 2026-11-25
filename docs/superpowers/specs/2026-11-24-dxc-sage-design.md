# DXC Sage — design

Date: 2026-11-24. Status: design approved, nothing built.

Small agentic harness, a simplified rebuild of Citadel. Providers: Claude and GPT only. Purpose: host SAP workflow tools for work. Reference build: `_references/mcp_architecture_PH.zip` (old MCP architecture; SAP tools in `mcp_server/src/capabilities/sap_*`).

## Decisions

| Topic | Decision |
|---|---|
| Location | `Applications/DXCSage/`, own git repo, ports from `26500–26999` |
| Services | Two: `sage_api` (FastAPI, async) and `sage_web` (Vue 3) |
| Auth | Local accounts, roles `admin` and `user`. Users are disabled, never deleted |
| Storage | SQLite (WAL), Docker compose, two containers |
| Providers | `Provider` interface, Claude and GPT adapters, one common event shape |
| Tools | Workflows (Python classes, fixed steps) built from shared task tools |
| SAP access | PyRFC. No hdbsql, no hdbuserstore. Table reads through standard `RFC_READ_TABLE`. Optional SSH per system, only for host files (see Optional SSH) |
| Limits | No usage limits. Usage counts only. Loop-turn cap per run is a safety cap, not a usage limit |
| Audit | Every request, task and admin action. Append-only, hash-chained |
| Chat delete | Soft delete. Runs, tool calls and audit stay |
| Write confirmation | Dropped for v1 (no `read_only`/`writes` flag) |
| Config and secrets | Everything in the DB, edited by admins in the UI. `.env` has only the bootstrap admin. Secrets encrypted with a master key file in its own Docker volume |
| SAP systems | Registered by admins (e.g. `TS3`) with an RFC account. Disabled, never deleted |
| Health checks | Per system and per workflow, read-only, results stored; a workflow runs on a system only if its check passes |

## Architecture

- `sage_api`: login, chats, agent loop (SSE streaming), providers, workflows, tasks, audit, usage. One process. `GET /health` open, answers within about 6 s (ServiceHub rule). Docker publish binds `0.0.0.0`, `extra_hosts: host.docker.internal:host-gateway`.
- `sage_web`: talks only to `sage_api`, relative URLs only. Style: `grey-console-frontend` skill (neutral grey surfaces, no blue backgrounds, blue only for text, icons, the active-item bar and focus rings). No reduced-motion handling.
- No config files. All settings and secrets live in the DB (see "Settings and secrets"). `.env` holds only the bootstrap admin (two lines, `.env.example` tracked).

```
Applications/DXCSage/
  sage_api/   src/{auth,chats,agent,providers,workflows,tasks,audit,usage,db}  tests/
  sage_web/   src/{pages,components,api}
  docker-compose.yml  .env.example  AGENTS.md  docs/
```

## Workflows and tasks (two layers)

The model sees only workflows. Workflows are built from tasks.

- **Task** = one small independent operation, e.g. `sap.read_table`, `sap.get_user_roles`, `sap.job_status`. A task has typed input and output, owns no workflow logic, and knows nothing about which workflow calls it.
- **Workflow** = the tool the model calls once. It runs fixed steps by calling tasks (and its own pure-Python logic), then returns one result.
- **Many workflows can use the same task.** Tasks live once in `tasks/`. Workflows import them. A task is never copied into a workflow.
- Each task call inside a workflow writes a `tool_steps` row and an audit event, and records which workflow called it.

```python
class Task(ABC):
    name: str
    Input: type[BaseModel]
    Output: type[BaseModel]
    async def run(self, ctx: TaskContext, data: Input) -> Output: ...

class Workflow(ABC):
    name: str
    description: str          # shown to the model
    Input: type[BaseModel]    # becomes JSON schema
    Output: type[BaseModel]
    needs_role: str = "user"
    async def run(self, ctx: WorkflowContext, data: Input) -> Output: ...

# inside a workflow:
rows = await ctx.task(ReadTable, ReadTable.Input(table="CVERS", fields=["COMPONENT", "RELEASE"]))
```

- Auto-discovery: tasks from `tasks/`, workflows from `workflows/`, one file each. A new SAP tool = one new workflow file, plus a task file only if no existing task fits.
- A failed task raises or returns `status="partial"`. The model gets a clear error string, never a stack trace. Fail closed: bad input, missing role or disabled workflow means refuse and log.
- Admin can enable or disable workflows. Tasks are not exposed to the model.
- A task declares its requirements (see "System health checks"). Each requirement carries a short setup guide (steps for the SAP Basis team) and, where needed, attached source (e.g. the ABAP for a `ZFM_*` function module). A workflow's guide is the union of its tasks' guides, so a shared task documents its setup once. A requirement that depends on input (`sap.read_table` can read any table) is declared by the workflow in `extra_requirements`, for example `TableReadable("CWBNTHEAD")`.

## SAP access (`SapRfc` service)

- One service owns the PyRFC connection pool and reads per-system connection data and the RFC account from the `systems` table (label, `ashost`, `sysnr`, `client`, user, decrypted password). `pyrfc` needs the SAP NW RFC SDK in the backend image (Docker prerequisite).
- `read_table(table, fields, where, rows)` calls `RFC_READ_TABLE` only:
  - 512-byte row limit: wider field lists are split into several calls with the same `WHERE`, each carrying the table's key fields (read from `DD03L`), then merged in Python by key. If the batches return different keys, or the table has no key fields, the read is rejected with a message to narrow the fields.
  - No joins. Workflows join in Python, one read per table.
  - Default `ROWCOUNT` cap (config). A cut result carries `truncated=true`.
  - On `TABLE_NOT_AVAILABLE` or an authorization error: clear error, no retry, no other path, audited.
- Writes only through named `ZFM_*` or BAPI tasks. Old function-module specs (`static/rfc/*.txt` in the reference zip) carry over.
- RFC user needs `S_RFC` for `RFC_READ_TABLE` plus `S_TABU_DIS` or `S_TABU_NAM` per table. Each workflow lists the tables it reads, so Basis can grant exactly those.

## Data (SQLite)

| Table | Purpose |
|---|---|
| `users` | role `admin` or `user`; disabled, never deleted |
| `chats` | soft delete (`deleted_at`) |
| `messages` | kept with the chat |
| `runs` | one per request or task: user, chat, provider, model, status (`running`, `waiting`, `done`, `failed`, `cancelled`), `resume_at`, times, token counts |
| `tool_calls` | one per workflow call: input, output, status, `run_id` |
| `tool_steps` | one per task call or step inside a workflow: task name, calling workflow, input, output, status |
| `audit_log` | append-only; triggers block UPDATE and DELETE; each row holds the hash of the previous row |
| `usage_counters` | per user and day: requests, tokens in and out, workflow calls, task calls |
| `settings` | key, JSON value, `is_secret`, `updated_by`, `updated_at`; secret values stored encrypted |
| `systems` | registered SAP systems: label, SID, description, `ashost`, `sysnr`, `client`, `rfc_user`, `rfc_password_enc`, `status` (`inactive`, `active`, `disabled`), timestamps. Never deleted |
| `system_health` | one row per system, workflow and requirement: result, message, checked_at |
| `sessions` | login sessions (hashed token, user, expiry) |
| `run_events` | per-run event log (text, tool start, steps, waiting, end); lets the UI reattach and replay after a disconnect |
| `workflow_systems` | one row per workflow and system: `status` (`setup`, `enabled`, `disabled`), per-system `settings` JSON (e.g. `default_variant`), `enabled_by`, timestamps. Never deleted |

Chat delete sets `deleted_at` and writes an audit event. It never touches `runs`, `tool_calls`, `tool_steps` or `audit_log`. Admins can read the records of deleted chats.

## Agent loop

- User message creates a `run` (`running`), audit `run.start`.
- Loop: send messages and workflow schemas to the provider, stream text over SSE, run requested workflows, append results, repeat. Cap on loop turns per run (setting `agent.max_turns`, default 10).
- Run ends `done`, `failed` or `cancelled`. User can cancel. Tokens and usage counters are written in the transaction that closes the run.
- Provider and model chosen per chat from an allowed list (setting `providers.models`); switching mid-chat allowed. A provider with no API key set is disabled and not offered.

## Settings and secrets

- No `.env` settings and no JSON configs. The only `.env` values are `SAGE_BOOTSTRAP_ADMIN_USER` and `SAGE_BOOTSTRAP_ADMIN_PASSWORD`. They are read only when no admin account exists; the first login forces a password change; later they are ignored. DB path and port are fixed in `docker-compose.yml`.
- `settings` table: key, JSON value, `is_secret`. Defaults are seeded in code on first start, so a fresh install runs with no files. Each change writes a `config.change` audit event (the value is not logged for secrets).
- Settings include: `agent.max_turns`, `providers.models`, Claude and GPT API keys (secret), `wait.backoff` and `wait.max_wait`, `health.max_age`, `sap.rowcount_cap`, `readiness.prerequisite_notes`. (Per-system values such as the readiness variant live on the workflow setup, not here.)
- Secrets (API keys, RFC passwords) are encrypted at rest (Fernet). The master key is a file generated on first start in its own Docker volume, separate from the SQLite volume. A stolen DB file or DB backup alone cannot be decrypted. Backups must cover both volumes, or secrets are re-entered after a restore.
- Secrets are write-only: no API returns them, the UI shows "set" or "not set", and audit stores "changed" without the value.
- Only admins read or change settings.

## System registry (SAP systems)

- Admin-only: register, edit, rotate credentials, enable or disable. Users see only label and SID of `active` systems, in the system picker.
- Registration form: label (e.g. `TS3`), SID, description, `ashost`, `sysnr`, `client`, and the RFC account (user, password). One RFC account per system in v1. SAP's own logs show the RFC user; Sage's audit shows which Sage user asked.
- On save, Sage runs a connect and login test. The system stays `inactive` until it passes. An admin can save a failed one as `inactive` and fix it later.
- Never deleted, because runs and audit rows point at systems.
- Audit events: `system.create`, `system.update`, `system.credentials`, `system.disable`, `system.health_check`.

## System health checks

Each task declares its requirements; a workflow's requirements are the union of its tasks'. `sap.read_table` declares its requirement once and every workflow that uses it inherits it.

| Requirement | Check (read-only) | On failure |
|---|---|---|
| `Reachable` | RFC connect and `RFC_PING` | dependents `blocked` |
| `LoginOk` | open a connection with the stored RFC account | dependents `blocked` |
| `FmExists(fm)` | read `TFDIR` through `RFC_READ_TABLE` | `fail` |
| `FmAuthorized(fm)` | `S_RFC` check for the account (unverified: `SUSR_USER_AUTH_FOR_OBJ_GET` remote-enabled and allowed; fallbacks: read `UST12`, or report `unknown`) | `fail` or `warn` |
| `TableReadable(table)` | `RFC_READ_TABLE` with `ROWCOUNT 1`; `TABLE_NOT_AVAILABLE` or an authorization error | `fail` |
| `SettingPresent(key)` | a required setting exists, e.g. a variant for this system | `warn` or `fail` |

- The check never calls a write or job-scheduling FM. A pass proves existence and authorization, not that the FM works.
- Results `pass`, `warn`, `fail`, `blocked` are stored per system, workflow and requirement in `system_health`, with the exact error.
- A workflow runs on a system only if it is `enabled` for that system (see "Workflow setup per system"), its last check is `pass` or `warn`, and the check is younger than `health.max_age` (default 24 h). Otherwise Sage re-checks first; if it fails the workflow refuses and lists the failed requirements. The workflow's system picker offers only systems that pass.
- Admin UI: matrix of systems by workflows, a detail view per cell, and "re-check" for a cell, a system or all systems.

## Workflow setup per system

A registered (`active`) system is not usable by a workflow until an admin sets that workflow up on it.

**Flow (admin only):** Workflows page, open a workflow, "Set up on a system", pick an `active` system. Sage then shows:
1. **Guide.** What must exist in that SAP system for this workflow to run (below).
2. **Per-system settings** the workflow declares, e.g. `default_variant` for the readiness check.
3. **Check.** "Run health check" runs the workflow's requirements on that system. Each guide step shows its live result (`pass`, `fail`, `blocked`, `warn`), so the guide works as a checklist that turns green.
4. **Enable.** Allowed when no requirement is `fail` or `blocked`. `warn` is allowed. A setup that is not enabled stays `setup`; disabling sets `disabled`. Rows are never deleted.

**Guide content.** Built from the declared requirements of the workflow's tasks. Written in code beside each requirement, filled in with this system's SID, client and RFC user. Per requirement:
- `FmExists(fm)`: create the function module in SE37 (function group, "Remote-Enabled" flag, interface), with the ABAP source attached (carried over from the old `static/rfc/*.txt`) and a note on transport to this system.
- `FmAuthorized(fm)`: add `S_RFC` (`RFC_TYPE` = `FUNC`, `RFC_NAME` = the function or its group, `ACTVT` = 16) to the RFC user's role.
- `TableReadable(table)`: add `S_TABU_NAM` (`TABLE` = the table, `ACTVT` = 03), or `S_TABU_DIS` for its authorization group.
- `SettingPresent(key)`: which Sage value to fill in.
- Reachable and login problems: network and RFC account hints, common SAP error texts.

The guide ends with one combined authorization table (object, field, value) that Basis can copy into a role. It can be copied as Markdown to hand to Basis. It is generated, never stored, so it always matches the current code.

**What it changes elsewhere**
- The health matrix has cells only for set-up workflows; the rest show "not set up".
- The model is offered only workflows that are `enabled` on at least one passing system, and its system argument lists only systems where the workflow is enabled and passing.
- Audit events: `workflow.setup`, `workflow.enable`, `workflow.disable`, `workflow.settings`.

## Durable runs (long-held workflows)

Some workflows wait hours on SAP (first one: readiness check). They hold one run open, and the run survives a server restart and a browser disconnect.

- A workflow sets `durable = True`. Its `run` is replayable: every `ctx.task(...)` and `ctx.wait(...)` result is stored in `tool_steps` under a step key (`<n>:<task name>`). On replay, a step that already has a stored result returns it without calling SAP again. So "schedule job" never runs twice.
- `ctx.wait(poll_task, input, until, backoff, max_wait)` polls a task until `until(result)` is true. Between polls the run is `waiting` with `resume_at` stored in `runs`. No coroutine stays blocked in memory for hours: a scheduler wakes the run at `resume_at`, replays the workflow to the wait step, and polls once.
- Backoff default: 10 s for 1 min, 1 min up to 5 min, 5 min up to 1 h, 15 min up to 3 h, 1 h up to 24 h (from the old watcher). `max_wait` default 24 h, then the run ends `failed` with `timed_out`.
- The agent loop is durable too: messages are already in the DB, and the pending `tool_calls` row is `running`. After a restart the loop is rebuilt from `messages` plus that row, and the workflow result is appended when the workflow ends.
- Browser disconnect: the run is server-side. The UI reattaches to the run and replays its events from `tool_steps` and `messages`. A `waiting` run shows its current step and next poll time.
- The user can cancel a `waiting` run. Cancel is audited. Replay never repeats a step that changed SAP, because stored results are returned instead.
- A workflow that is not `durable` keeps the old rule: a restart marks it `failed`.

## Audit

- One writer, `audit(event, actor, run_id, detail)`. All code goes through it.
- Events: `auth.login`, `auth.fail`, `chat.create`, `chat.delete`, `run.start`, `run.end`, `tool.call`, `tool.step`, `tool.end`, `admin.user_*`, `config.change`.
- Workflow and task inputs and outputs stored in full. Secrets scrubbed by key name before write.
- Admin UI: filter, CSV export, "verify chain".

## Frontend (`sage_web`)

### Layout

- **Top bar**, 56px, dark grey in both themes: logo, divider, product name, breadcrumb, Light/Dark/System switch, user.
- **Main menu**, left sidebar: 216px with labels, or a 60px icon-only strip. Collapse button at the bottom and Ctrl+B. State remembered per browser. Every item has an icon and a tooltip.
- **Chat list**, left of the conversation on the Chat page: 296px, or a 56px rail with a "+" button and one status dot per chat. Collapse button in its header and Ctrl+Shift+B. State remembered.
- **1000px and below**: the main menu stays a 60px icon-only left sidebar (no tab row, no expand control; labels only as tooltips). The chat list becomes a 320px slide-in drawer opened by a "Chats" button, with a scrim; Esc closes it and focus moves in and back.
- No horizontal page scroll at 320px.

### Pages

- Login.
- Chat: chat list, new chat, streaming messages, workflow calls as collapsible cards with their steps, provider and model picker, cancel button, delete with confirm modal.
- My usage: own counts by day.
- Admin only: Users (create, disable, reset password, change role), Usage (per user and day), Runs (including deleted chats; full call and step detail), Audit (filter, export, verify chain), Workflows (list; open one to set it up on a system, see its guide and per-system settings, enable or disable), Systems (register, edit, rotate RFC credentials, enable or disable), Health (matrix of systems by workflows, with re-check), Settings (all settings; secret values write-only).

## Errors

- Provider error or timeout: run `failed`, short user message, details to `runs` and audit. No auto-retry in v1.
- Browser disconnect mid-run: run finishes; reload shows the result.
- Server restart: a run in `waiting` or `running` whose workflow is `durable` is resumed on startup (see "Durable runs"). Any other run still `running` is marked `failed`, with an audit event.
- Failed logins rate limited per username and IP, logged as `auth.fail`.

## Tests (small)

- Audit hash chain: tamper detection; UPDATE and DELETE blocked.
- Chat soft delete keeps runs, calls, steps and audit.
- Agent loop with a fake provider: tool call, loop cap, cancel.
- `ctx.task` writes a step row, with the calling workflow, even on failure.
- Durable replay: a restart in the middle of `ctx.wait` resumes the run; the schedule step is not called a second time (fake RFC counts calls).
- Two workflows share one task without copying it.
- `read_table` splitting of wide field lists, with a fake RFC.
- Role check on admin routes, including Systems, Health and Settings.
- Secrets: stored encrypted, never returned by any API, scrubbed from audit.
- Bootstrap admin: created only when no admin exists; first login forces a password change.
- Health check: a failed `Reachable` marks dependent requirements `blocked`; a workflow refuses to run on a system whose check failed.
- Workflow setup: a system must be `active` to be set up; enabling is refused while a requirement is `fail` or `blocked`; a workflow not enabled on a system is not offered for it; the generated guide fills in SID, client and RFC user and lists every requirement of the workflow.

## Out of scope for v1

Write-confirmation flag, SSO, usage limits, providers other than Claude and GPT, auto-retry, Postgres, trace mode of the old `auth_requirements` tool.

## First workflow: SAP Readiness Check (`sap_readiness_check`)

Ported from the reference zip, `mcp_server/src/capabilities/sap_readiness_check/`. One durable workflow, one long-held run. Input: `system_name` (config label, not SID), optional `variant_name`.

Steps (all PyRFC; custom FMs must exist on the target system, specs in the old `static/rfc/*.txt`):
1. `check_notes`: read `CWBNTHEAD` through `sap.read_table`; for each missing required note call `ZFM_RC_NOTES_DOWNLOAD`, re-read until it appears or `download_wait_seconds` runs out. A missing required note stops the run. Conditional notes (2827612) are reported, never block. `require_implemented` stays in the notes config.
2. `pick_variant`: `variant_name` or the system's `default_variant` from its workflow setup; validate against `VARID` through `sap.read_table`. No variant means fail.
3. `start_analysis`: `ZFM_RC_START_ANALYSIS` schedules `RC_COLLECT_ANALYSIS_DATA`; returns job name and count (stored, never repeated on replay).
4. `wait_for_job`: `ctx.wait` polling `ZFM_CHECK_JOB_STATUS` until status `F` (finished) or `X` (failed).
5. `download_archive`: `ZFM_RC_FETCH_ANALYSIS` returns the ZIP; saved to a data folder; size and name recorded. Uploading to SAP Readiness Check or SAP for Me stays manual.

Tasks it uses: `sap.read_table` and `sap.job_status` (`ZFM_CHECK_JOB_STATUS`) are shared and reusable by any workflow; `rc.notes_download`, `rc.start_analysis` and `rc.fetch_archive` are specific to readiness check.

Settings (DB, seeded with defaults, admin-editable with an audit event; replace the old `prerequisite_notes.json` and the `get_notes`/`set_notes` tools): `readiness.prerequisite_notes` (required and conditional notes). The old `variants.json` becomes a per-system value on the workflow setup: `default_variant`. Tables read: `CWBNTHEAD`, `CWBNTCUST` (implementation status, unverified on a live system), `VARID`.

Result: job name and count, final status, file path and size, notes report. The UI shows the ZIP as a download. Old email watchers and recipient lists are not ported in v1: the chat shows the result when the run ends. Old audit, `listSystems` and `listWatchers` tools are replaced by Sage's audit, system config and runs list.

## Open items for later

- Other workflows to port: role remediation (auth change, user-role change, obsolete tcode scan, SoD check), addon uninstall guide, authorization requirements of a function module. SUM monitoring needs SSH or HTTP, not PyRFC, so it stays out until a connector decision.
- The old SSH-based `sys check` has no PyRFC equivalent yet.
- Email notification on run end (old watcher feature) as a generic task, if wanted later.

## Custom ABAP object names (per system)

Custom function modules and function groups (`ZFM_*`, `ZFG_*`) have a fixed **`abap_object_id`**: the ID in code, tasks, requirements and the setup guide text. A system with another naming convention can map an ID to its own name in the workflow setup guide ("Object names on this system"); the ID is never changed.

- Stored in `abap_names(system_id, abap_object_id, name)`, unique per system and name. Empty by default, so a system without overrides behaves exactly as before. Naming an object by its ID again removes the override.
- `SapRfc.call` translates the ID to the system's name for every call. Health checks (`TFDIR` read, `S_RFC` rows) and the guide (text, ABAP source, authorization table) use the system's name and show the ID next to it.
- Names are checked on save: optional `/NAMESPACE/` prefix, a letter first, letters, digits and underscores, at most 30 characters, unique per system, only for IDs some workflow uses. Admin only; audited as `system.abap_name`.
- Saving a name re-runs the health check of every workflow set up on that system, so the stored result matches the new name.
- Not renamed: standard SAP objects (`RFC_READ_TABLE`, `TFDIR`, tables) and the ID stored in task steps.

## Authorization coverage (in the health check)

Every workflow's health check ends with an `auth_coverage` requirement that lists **all** authorization values the workflow needs and compares them with the RFC user, so the admin can ask the security team once instead of finding one blocker per run.

- **Needed values:** the declared requirements (`S_RFC` per function module and group, `S_TABU_NAM` per table) plus a static scan of each function module with the custom RFC `ZFM_AUTH_REQ_LIST` (every `AUTHORITY-CHECK` it contains, following the calls it makes). `DUMMY` checks are skipped.
- **Per value:** `granted`, `missing`, `review` (value decided at run time, or a call the scan could not follow) or `unknown` (the account's authorizations could not be read). Table authorizations count as granted when the table read test passed.
- **Reliability:** `missing` is reliable (the value is in none of the account's authorizations). `granted` is optimistic because the account's values are read per field, not per authorization. Unverified on a real system: `SUSR_USER_AUTH_FOR_OBJ_GET` being remote-enabled and returning FIELD/VON/BIS.
- **Status:** any `missing` fails the requirement and blocks enabling; `review`, `unknown` or a scan that could not run only warn. `ZFM_AUTH_REQ_LIST` is a recommended, not required, function module (`level="warn"`): without it the declared values are still checked.
- **Stored** in `auth_checks` (replaced on every check). The setup guide shows them with the object, field, value, which function module needs them and the status, and "Copy request for security" copies one grouped text of everything missing or to be confirmed.
- Requirements have a `level`: `warn` turns a failure of that requirement into a warning.

## Optional SSH (per system)
Added for SUM monitoring, whose state lives in files on the host, not in RFC-reachable tables.
- **Registration:** an admin may add SSH access when registering a system, or later on the system's page: host (default the application server), port, user, and a password or a private key without passphrase. It is optional. A system without it works as before.
- **Storage:** table `system_ssh` (one row per system). The secret is encrypted with the master key like the RFC password, never returned by any API, and audited as changed only.
- **Host key pinning:** Sage never logs in to an unknown server. The test reads the key the server presents; the admin compares the fingerprint and trusts it; only then does a login happen. A new host or port drops the trust. A changed key blocks the login and the test says so.
- **What can run:** `SapSsh` has fixed methods only: `read_file` (tail of a validated absolute path), `file_readable`, `process_running`. No method takes a command string. Workflows and the model cannot run a command.
- **Health:** `SshLogin` (SSH set up, key trusted, login works) and `FileReadable(path)` (`{SID}` is replaced by the system ID) are requirements like the RFC ones. They show in the setup guide.
- **Not included:** starting or stopping SUM, and e-mail or Teams alerts.
