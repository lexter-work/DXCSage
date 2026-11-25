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
| `sap_user_sod_check` | Checks one user's roles (composite roles expanded) for segregation-of-duties conflicts. | No | none | `sod.matrix` |
| `sap_addon_uninstall_guide` | For up to 10 add-ons: uninstallable by SAINT, plugin class, object counts, risk, and a Basis work order. | No | none | `addon.protected_components` |
| `sap_user_role_review` | Previews a request to assign or remove roles for users: validity, no-ops, SoD before and after. | No | none | `sod.matrix`, `rolechange.max_entries` |
| `sap_user_role_change` | Applies that request with `BAPI_USER_ACTGROUPS_ASSIGN` and reads each user back. Runs the review first and refuses on an error or a new CRITICAL conflict. | **Yes** | none (standard BAPIs) | same as above |
| `sap_role_auth_review` | Previews a request to change role authorizations: roles and values exist, policy, SoD before and after. | No | none | `sod.matrix`, `rolechange.policy` |
| `sap_role_auth_change` | Adds, removes or modifies authorization values and removes transaction codes on roles, then regenerates derived roles. Runs the review first and refuses on an error, a policy violation or a new CRITICAL conflict. | **Yes** | `ZFM_RR_ROLE_AUTH_CHANGE`, `ZFM_RR_TCODE_REMOVE`, `ZFM_RR_DERIVED_REGENERATE` | same as above |

Not ported from the old tool: the Excel upload and report steps, and the AI review of free-form policy documents.

### Setting up a workflow on a system
Open the workflow on the Workflows page, choose the system and follow the setup guide. It lists every requirement (connection, function modules, tables, authorizations, settings) with its status. The ABAP objects page shows, for each custom object, its process flow, how to create it and the ABAP code to paste, using the names of the chosen system. Each system may name a custom object differently: enter its name in the guide and Sage keeps the fixed object ID. The health check compares every authorization a workflow needs with the RFC user, so you can send the security team one request with everything that is missing.

The two workflows that write to SAP ask the model to get the requester's confirmation first, and their reviews are the gate: a write never runs after a failed review. Test the write function modules in a sandbox client before any other system.

## Backups
Back up both volumes: `sage_data` (SQLite) and `sage_keys` (the master key). The key alone is useless and the DB without the key cannot decrypt stored passwords.

## Not verified yet
pyrfc against a real SAP system, the Claude and GPT network calls, the Docker images, and the custom `ZFM_*` function modules (specs and code are in the setup guide and on the ABAP objects page). The table and field names the read-only workflows use (`AGR_*`, `PAT03`, `PAT08`, `TADIR` and others) are not confirmed on a live system either.
