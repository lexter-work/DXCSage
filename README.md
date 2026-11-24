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
4. Workflows: open `sap_readiness_check`, set it up on the system, follow the guide, run the health check, enable it.
5. Chat: ask for a readiness check on that system.

## Backups
Back up both volumes: `sage_data` (SQLite) and `sage_keys` (the master key). The key alone is useless and the DB without the key cannot decrypt stored passwords.

## Not verified yet
pyrfc against a real SAP system, the Claude and GPT network calls, the Docker images, and the custom `ZFM_*` function modules (specs are in the setup guide).
