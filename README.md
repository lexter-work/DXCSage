# DXC Sage

Small agentic harness (Claude and GPT) with SAP workflow tools. Two services: `sage_api` (port 29700) and `sage_web` (port 29701). Design: `docs/superpowers/specs/2026-11-24-dxc-sage-design.md`.

## Run with Docker
Put the SAP NW RFC SDK and a `pyrfc` wheel in `sage_api/vendor/` (licensed, not in git; `pyrfc` is yanked on PyPI, so it is not installed from there), then:

    docker compose up -d --build

Open `http://localhost:29701`. Copy `.env.example` to `.env` and set the bootstrap admin before the first start; the first sign-in forces a password change. Everything else (API keys, SAP systems, settings) is set in the app, as an admin.

## Run without Docker (development)

    cd sage_api; uv run uvicorn sage.app:create_app --factory --port 29700
    cd sage_web; pnpm install; pnpm dev

## First steps
1. Sign in as the bootstrap admin and change the password.
2. Settings: set the Claude and/or GPT API key.
3. Systems: register a SAP system and its RFC account.
4. Workflows: open a workflow (for example `sap_readiness_check`), set it up on the system, follow the guide, run the health check, enable it.
5. Chat: ask for it on that system, for example a readiness check.

## Workflows
The model sees workflows only. Each one is built from shared tasks, and every task call is a stored, audited step. A workflow runs on a system only after an admin sets it up there, the health check passes and it is enabled. A new workflow module in `sage_api/src/sage/workflows/` is found automatically.

| Workflow | What it does | Writes to SAP | Custom ABAP objects | Settings |
|---|---|---|---|---|
| `sap_readiness_check` | Checks the prerequisite SAP Notes (downloads missing ones), schedules `RC_COLLECT_ANALYSIS_DATA`, waits for the job and downloads the ZIP. Long-running, survives restarts. | Schedules jobs | `ZFM_RC_NOTES_DOWNLOAD`, `ZFM_RC_START_ANALYSIS`, `ZFM_CHECK_JOB_STATUS`, `ZFM_RC_FETCH_ANALYSIS` | `readiness.prerequisite_notes`, default variant per system |
| `sap_obsolete_tcodes` | Finds obsolete transaction codes in role menus (SU25 step 2D, all roles). Returns role and transaction pairs and a CSV. Long-running. | Schedules a job | `ZFM_RR_TC_OBS_START`, `ZFM_RR_TC_OBS_FETCH`, `ZFM_CHECK_JOB_STATUS` | none |
| `sap_auth_requirements` | Lists the authorizations the RFC user needs for every installed workflow, or one. | No | `ZFM_AUTH_REQ_LIST` | none |
| `sap_record_policy_review` | Stores the AI's findings after it read a policy document against a request. Needs no system. | No (internal) | none | none |
| `sap_sum_status` | Reads the state of the SUM session on the host (running, waiting for input, error, possible hang, process dead, completed, offline) with phase, progress, estimated end and the next action. For an error it matches SAPup.log with 13 known signatures. Needs **optional SSH access** on the system. | No | none | none |
| `sap_user_sod_check` | Checks one user's roles (composite roles expanded) for segregation-of-duties conflicts. | No | none | `sod.matrix` |
| `sap_addon_uninstall_guide` | For up to 10 add-ons: uninstallable by SAINT, plugin class, object counts, risk, and a Basis work order. | No | none | `addon.protected_components` |
| `sap_user_role_review` | Previews a request to assign or remove roles for users: validity, no-ops, SoD before and after. | No | none | `sod.matrix`, `rolechange.max_entries` |
| `sap_user_role_change` | Applies that request with `BAPI_USER_ACTGROUPS_ASSIGN` and reads each user back. Runs the review first and refuses on an error or a new CRITICAL conflict. | **Yes** | none (standard BAPIs) | same as above |
| `sap_role_auth_review` | Previews a request to change role authorizations: roles and values exist, policy, SoD before and after. | No | none | `sod.matrix`, `rolechange.policy` |
| `sap_role_auth_change` | Adds, removes or modifies authorization values and removes transaction codes on roles, then regenerates derived roles. Runs the review first and refuses on an error, a policy violation or a new CRITICAL conflict. | **Yes** | `ZFM_RR_ROLE_AUTH_CHANGE`, `ZFM_RR_TCODE_REMOVE`, `ZFM_RR_DERIVED_REGENERATE` | same as above |

Not ported from the old tool: the Excel report workbook and the change document. A system-less workflow, `sap_record_policy_review`, is used by the policy review below.

### Setting up a workflow on a system
Open the workflow on the Workflows page, choose the system and follow the setup guide. It lists every requirement (connection, function modules, tables, authorizations, settings) with its status. The ABAP objects page shows, for each custom object, its process flow, how to create it and the ABAP code to paste, using the names of the chosen system. Each system may name a custom object differently: enter its name in the guide and Sage keeps the fixed object ID. The health check compares every authorization a workflow needs with the RFC user, so you can send the security team one request with everything that is missing.

SSH is optional and per system. An admin can add it when registering a system or later on its page: host, port, user, and a password or a private key without passphrase. Sage will not log in until an admin has compared and trusted the host key of the server. SSH is used only to read files and check processes on the host (for `sap_sum_status`); Sage runs no typed or model-written command. Starting and stopping SUM, and e-mail alerts, are not part of Sage.

The two workflows that write to SAP ask the model to get the requester's confirmation first, and their reviews are the gate: a write never runs after a failed review. Test the write function modules in a sandbox client before any other system.

## Change requests: chat or Excel
For `sap_user_role_review`, `sap_user_role_change`, `sap_role_auth_review` and `sap_role_auth_change` the changes can come two ways, and the user does not need Excel:
- **Describe them in the chat.** The model fills the change list from what the user wrote, runs the review, shows the findings, and calls a change workflow only after the user confirmed the exact list.
- **Attach an Excel file** with **Attach Excel** in the chat. The file is read for that user only. Three templates are in the **Templates** menu of the chat (also at `api/templates/<kind>.xlsx`): user roles (`Username, Role, Action`), role authorizations (`Role, Object, Field, Current Value, Requested Value, Action`) and remove transaction codes (`Role, Tcode`; the CSV of `sap_obsolete_tcodes` fits). The sample rows are on a separate sheet, so uploading an untouched template changes nothing. Organization-level fields (`$`) are not supported.

## Policies (AI review of written rules)
On the Policies page an admin keeps policy documents (paste text, or load a .txt, .md or .docx). A policy marked as required applies to every role and user-role request; others apply when named in the request. The structured rules are still checked by code. For a written policy, the review gives the model the policy text and a hash of the exact request; the model reads one against the other and records its findings with `sap_record_policy_review`; the next review uses them. Any finding blocks the change workflows. A verdict counts only for that exact request and that exact text, the first verdict stands, and an admin can clear reviews. This is the model's judgment, not an access control.

## Email notifications
Workflows can send an email when they change state.
1. Settings: set `email.smtp_host`, `email.smtp_port`, `email.security`, optionally `email.smtp_user` and `email.smtp_password`, `email.from_address`, then `email.enabled`.
2. Email groups page: make groups of recipients. A member is just an email address, so people outside Sage can be added. Send a test email there.
3. Workflows page, **Email notifications** on a workflow: tag one or more groups and choose the states: started, waiting (long runs), completed, failed, cancelled, and for a status workflow its result states (for example `sap_sum_status` can mail on ERROR, POSSIBLE_HANG or PROCESS_DEAD).

A group can get its events immediately, as an hourly digest, or as a daily digest (sent from `email.digest_hour_utc`, UTC). An email states the workflow, the system, who asked, the state and, for a failure, the error text. It never contains results. Recipients get a blind copy, so they cannot see each other. A failed send never affects the run; it shows under Recent emails on the Email groups page. Each state of one run is mailed once, also after a restart. A result-state email (for example SUM is in ERROR) is sent only when that state differs from the previous run of the same workflow, system and input, so a schedule that keeps finding the same error mails once. Status workflows can also remind: while the result stays ERROR or POSSIBLE_HANG (`sap_sum_status`), a reminder goes out every `email.reminder_minutes` (default 60; 0 turns it off). To get emails without anyone asking, add a schedule.

## Schedules
The Schedules page runs a workflow again and again without a chat, as an admin account. Pick the workflow and system, fill in its other inputs, and choose every N minutes (5 to 10080) or daily at a time (UTC). Each run goes through the same checks, audit and email rules as a chat run, and appears on the Runs page under the schedule's name. Long-running workflows resume after a restart as usual. If the previous run is still going when the next is due, the new one is skipped. After downtime, a missed run happens once.

Only workflows that opt in with `schedulable = True` can be scheduled: `sap_sum_status`, `sap_user_sod_check`, `sap_auth_requirements` and `sap_addon_uninstall_guide` (read-only), and `sap_readiness_check` and `sap_obsolete_tcodes`, which start SAP jobs and therefore run at most once a day. Every workflow that changes roles or users can only be run from a chat. Scheduled runs are not counted as user requests in the usage numbers.

For monitoring, schedule `sap_sum_status` every 10 minutes, tag an email group to its `ERROR`, `POSSIBLE_HANG` and `PROCESS_DEAD` results, and enable email.

## Backups
Back up both volumes: `sage_data` (SQLite) and `sage_keys` (the master key). The key alone is useless and the DB without the key cannot decrypt stored passwords.

## Not verified yet
pyrfc against a real SAP system, the Claude and GPT network calls, the Docker images, and the custom `ZFM_*` function modules (specs and code are in the setup guide and on the ABAP objects page). The table and field names the read-only workflows use (`AGR_*`, `PAT03`, `PAT08`, `TADIR` and others) are not confirmed on a live system either.
