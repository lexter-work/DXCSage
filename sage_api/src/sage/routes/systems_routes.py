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
