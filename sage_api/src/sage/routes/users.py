from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from sage.auth import AuthError
from sage.deps import admin_user

router = APIRouter(prefix="/api/users")


class NewUser(BaseModel):
    username: str
    password: str
    role: str = "user"


class UserPatch(BaseModel):
    role: str | None = None
    disabled: bool | None = None


class Reset(BaseModel):
    password: str


@router.get("")
async def list_users(request: Request, admin: dict = Depends(admin_user)):
    return await request.app.state.services.auth.list_users()


@router.post("")
async def create_user(body: NewUser, request: Request, admin: dict = Depends(admin_user)):
    try:
        uid = await request.app.state.services.auth.create_user(body.username, body.password, body.role, admin["username"])
    except AuthError as e:
        raise HTTPException(400, e.code)
    return {"id": uid}


@router.patch("/{user_id}")
async def patch_user(user_id: int, body: UserPatch, request: Request, admin: dict = Depends(admin_user)):
    auth = request.app.state.services.auth
    try:
        if body.role is not None:
            await auth.set_role(user_id, body.role, admin["username"])
        if body.disabled is not None:
            await auth.set_disabled(user_id, body.disabled, admin["username"])
    except AuthError as e:
        raise HTTPException(400, e.code)
    return {"ok": True}


@router.post("/{user_id}/reset-password")
async def reset_password(user_id: int, body: Reset, request: Request, admin: dict = Depends(admin_user)):
    try:
        await request.app.state.services.auth.reset_password(user_id, body.password, admin["username"])
    except AuthError as e:
        raise HTTPException(400, e.code)
    return {"ok": True}
