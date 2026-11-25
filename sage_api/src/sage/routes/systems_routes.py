from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from sage.deps import admin_user, current_user
from sage.sap.ssh import SshError, fingerprint
from sage.systems import SystemsError
from sage.workflows.base import all_abap_objects

router = APIRouter(prefix="/api/systems")


class SshIn(BaseModel):
    """Optional SSH access to the host of the system. Only used to read files and check processes."""
    host: str = Field(default="", pattern=r"^[A-Za-z0-9._-]{0,253}$")      # empty = the application server host of the system
    port: int = Field(default=22, ge=1, le=65535)
    user: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    auth: Literal["password", "key"] = "password"
    secret: str = Field(min_length=1, max_length=20000)


class NewSystem(BaseModel):
    label: str = Field(pattern=r"^[A-Za-z0-9_-]{1,20}$")
    sid: str = Field(pattern=r"^[A-Z0-9]{3}$")
    description: str = ""
    ashost: str = Field(min_length=1)
    sysnr: str = Field(pattern=r"^\d{2}$")
    client: str = Field(pattern=r"^\d{3}$")
    rfc_user: str = Field(min_length=1)
    rfc_password: str = Field(min_length=1)
    ssh: SshIn | None = None


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


class AbapName(BaseModel):
    object_id: str
    name: str


@router.put("/{system_id}/abap-names")
async def abap_name(system_id: int, body: AbapName, request: Request, admin: dict = Depends(admin_user)):
    """Name a custom ABAP object the way this system does. Health is re-checked for the workflows set up here, so it matches the new name."""
    svc = request.app.state.services
    if not await svc.systems.get(system_id):
        raise HTTPException(404, "not_found")
    try:
        await svc.systems.set_abap_name(system_id, body.object_id, body.name, admin["username"], all_abap_objects(svc.workflows))
    except SystemsError as e:
        raise HTTPException(400, str(e))
    for wf in svc.workflows:
        if any(b["system_id"] == system_id for b in await svc.setup.bindings(wf)):
            await svc.health.check(system_id, wf, admin["username"])
    return {"ok": True, "names": await svc.systems.abap_names(system_id)}


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


def _same_key(a: str, b: str) -> bool:
    return a.split()[:2] == b.split()[:2]


@router.get("/{system_id}/ssh")
async def ssh_get(system_id: int, request: Request, admin: dict = Depends(admin_user)):
    return await request.app.state.services.systems.ssh_public(system_id)


@router.put("/{system_id}/ssh")
async def ssh_put(system_id: int, body: SshIn, request: Request, admin: dict = Depends(admin_user)):
    svc = request.app.state.services
    system = await svc.systems.get(system_id)
    if not system:
        raise HTTPException(404, "not_found")
    try:
        await svc.systems.set_ssh(system_id, body.host or system["ashost"], body.port, body.user, body.auth, body.secret, admin["username"])
    except SystemsError as e:
        raise HTTPException(400, str(e))
    return await svc.systems.ssh_public(system_id)


@router.delete("/{system_id}/ssh")
async def ssh_delete(system_id: int, request: Request, admin: dict = Depends(admin_user)):
    await request.app.state.services.systems.clear_ssh(system_id, admin["username"])
    return {"ok": True}


@router.post("/{system_id}/ssh/test")
async def ssh_test(system_id: int, request: Request, admin: dict = Depends(admin_user)):
    """Stage 1: read the key the server presents. Stage 2 (only once an admin trusted it): log in."""
    ssh = request.app.state.services.ssh
    try:
        p = await ssh.params(system_id)
        line = await ssh.host_key(p.host, p.port)
    except SshError as e:
        return {"ok": False, "stage": "setup" if e.code == "NOT_SET_UP" else "connect", "message": e.message}
    fp = fingerprint(line)
    if not p.host_key:
        return {"ok": False, "stage": "host_key", "needs_trust": True, "fingerprint": fp,
                "message": "The host key is not trusted yet. Compare the fingerprint with the one of the server, then trust it."}
    if not _same_key(line, p.host_key):
        return {"ok": False, "stage": "host_key", "changed": True, "fingerprint": fp,
                "message": "The server presents a different host key than the trusted one. Do not continue unless the server was reinstalled."}
    try:
        await ssh.test(p)
    except SshError as e:
        return {"ok": False, "stage": "login" if e.code == "LOGIN" else "connect", "message": e.message}
    return {"ok": True, "stage": None, "message": "", "fingerprint": fp}


class Trust(BaseModel):
    fingerprint: str


@router.post("/{system_id}/ssh/trust")
async def ssh_trust(system_id: int, body: Trust, request: Request, admin: dict = Depends(admin_user)):
    """Trust the key the server presents now, but only if its fingerprint is the one the admin saw and confirmed."""
    svc = request.app.state.services
    try:
        p = await svc.ssh.params(system_id)
        line = await svc.ssh.host_key(p.host, p.port)
    except SshError as e:
        raise HTTPException(400, e.message)
    if fingerprint(line) != body.fingerprint:
        raise HTTPException(409, "The server now presents a different host key. Test again.")
    await svc.systems.trust_ssh_host_key(system_id, line, admin["username"])
    return await svc.systems.ssh_public(system_id)
