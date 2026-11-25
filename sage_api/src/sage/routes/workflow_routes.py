from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from sage.deps import admin_user, current_user
from sage.guide import build_guide, guide_markdown
from sage.sap.rfc import RfcError
from sage.tasks.base import TaskContext
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


@router.get("/workflows/{name}/systems/{system_id}/settings/{key}/options")
async def setting_options(name: str, system_id: int, key: str, request: Request, admin: dict = Depends(admin_user)):
    """Valid values for a setting, read from the system. SAP errors come back in the body so the page can fall back to typing."""
    svc = _svc(request)
    wf = svc.workflows.get(name)
    system = await svc.systems.get(system_id)
    if not wf or not system or not any(sp.key == key and sp.lookup for sp in wf.binding_settings):
        raise HTTPException(404, "not_found")
    task_ctx = TaskContext(system_id, svc.rfc, svc.settings, {}, svc.data_dir, system["label"])
    try:
        return {"options": await wf.setting_options(key, task_ctx), "error": None}
    except RfcError as e:
        return {"options": [], "error": f"{e.code}: {e.message}"}


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
    g = build_guide(svc.workflows[name], system, await svc.health.latest(system_id, name), await svc.systems.abap_names(system_id), await svc.health.auth_coverage(system_id, name))
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
