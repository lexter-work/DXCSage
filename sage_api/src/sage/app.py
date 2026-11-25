"""FastAPI app factory. Services are built in lifespan (see services.py)."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from sage.routes import admin_routes, auth_routes, chat_routes, email_routes, systems_routes, users, workflow_routes
from sage.services import build_services


def create_app(*, data_dir=None, key_dir=None, connector=None, providers=None,
               workflows=None, env=None, clock=None, ssh_connector=None, ssh_host_key=None, mail_sender=None) -> FastAPI:
    data_dir = data_dir or os.getenv("SAGE_DATA_DIR", ".data")
    key_dir = key_dir or os.getenv("SAGE_KEY_DIR", ".keys")

    @asynccontextmanager
    async def lifespan(app):
        svc = await build_services(data_dir=data_dir, key_dir=key_dir, connector=connector,
                                   providers=providers, workflows=workflows, clock=clock,
                                   ssh_connector=ssh_connector, ssh_host_key=ssh_host_key, mail_sender=mail_sender)
        app.state.services = svc
        await svc.auth.ensure_bootstrap_admin(os.environ if env is None else env)
        await svc.agent.recover_on_startup()
        svc.agent.start_scheduler()
        yield
        await svc.agent.stop_scheduler()
        await svc.db.close()

    app = FastAPI(title="DXC Sage", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    for r in (auth_routes.router, users.router, systems_routes.router, workflow_routes.router, chat_routes.router, admin_routes.router, email_routes.router):
        app.include_router(r)
    return app
