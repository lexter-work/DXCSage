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
- UI work follows `mockup/skills/dxc-ui-design/SKILL.md` (DXC 2026 brand). Reference screens: `mockup/DXCSage_brand_mockup.html`.
