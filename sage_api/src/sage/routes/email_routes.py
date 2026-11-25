from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from sage.deps import admin_user
from sage.emailer import EmailError, event_catalog

router = APIRouter(prefix="/api")


class Member(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(default="", max_length=80)


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=300)
    members: list[Member] = Field(default_factory=list, max_length=200)


class Rule(BaseModel):
    group_id: int
    events: list[str]


class Rules(BaseModel):
    rules: list[Rule]


class Test(BaseModel):
    to: str


def _svc(request):
    return request.app.state.services.email


async def _guard(coro):
    try:
        return await coro
    except EmailError as e:
        raise HTTPException(400, str(e))


@router.get("/email/groups")
async def groups(request: Request, admin: dict = Depends(admin_user)):
    return await _svc(request).groups()


@router.get("/email/groups/{group_id}")
async def group(group_id: int, request: Request, admin: dict = Depends(admin_user)):
    g = await _svc(request).group(group_id)
    if not g:
        raise HTTPException(404, "not_found")
    return g


@router.post("/email/groups")
async def create_group(body: GroupIn, request: Request, admin: dict = Depends(admin_user)):
    svc = _svc(request)
    gid = await _guard(svc.save_group(None, body.name, body.description, [m.model_dump() for m in body.members], admin["username"]))
    return await svc.group(gid)


@router.put("/email/groups/{group_id}")
async def update_group(group_id: int, body: GroupIn, request: Request, admin: dict = Depends(admin_user)):
    svc = _svc(request)
    if not await svc.group(group_id):
        raise HTTPException(404, "not_found")
    await _guard(svc.save_group(group_id, body.name, body.description, [m.model_dump() for m in body.members], admin["username"]))
    return await svc.group(group_id)


@router.delete("/email/groups/{group_id}")
async def delete_group(group_id: int, request: Request, admin: dict = Depends(admin_user)):
    await _svc(request).delete_group(group_id, admin["username"])
    return {"ok": True}


@router.get("/email/status")
async def status(request: Request, admin: dict = Depends(admin_user)):
    """Is sending set up? The UI shows a hint with a link to the settings when not."""
    s = request.app.state.services.settings
    return {"ready": bool(await s.get("email.enabled") and await s.get("email.smtp_host") and await s.get("email.from_address"))}


@router.post("/email/test")
async def test(body: Test, request: Request, admin: dict = Depends(admin_user)):
    await _guard(_svc(request).send_test(body.to, admin["username"]))
    return {"ok": True}


@router.get("/email/log")
async def log(request: Request, admin: dict = Depends(admin_user)):
    return await _svc(request).log()


@router.get("/workflows/{name}/notifications")
async def get_rules(name: str, request: Request, admin: dict = Depends(admin_user)):
    svc = request.app.state.services
    if name not in svc.workflows:
        raise HTTPException(404, "not_found")
    return {"events": [{"key": k, "label": v} for k, v in event_catalog(svc.workflows[name]).items()], "rules": await svc.email.rules(name)}


@router.put("/workflows/{name}/notifications")
async def set_rules(name: str, body: Rules, request: Request, admin: dict = Depends(admin_user)):
    svc = request.app.state.services
    if name not in svc.workflows:
        raise HTTPException(404, "not_found")
    await _guard(svc.email.set_rules(name, [r.model_dump() for r in body.rules], admin["username"]))
    return {"rules": await svc.email.rules(name)}
