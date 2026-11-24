from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from sage.auth import AuthError
from sage.deps import current_user

router = APIRouter(prefix="/api/auth")


class Login(BaseModel):
    username: str
    password: str


class ChangePassword(BaseModel):
    old: str
    new: str


@router.post("/login")
async def login(body: Login, request: Request, response: Response):
    svc = request.app.state.services
    try:
        token = await svc.auth.login(body.username, body.password, request.client.host if request.client else "?")
    except AuthError as e:
        raise HTTPException(429 if e.code == "rate_limited" else 401, e.code)
    response.set_cookie("sage_session", token, httponly=True, samesite="lax", max_age=7 * 86400)
    return {"ok": True}


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("sage_session")
    if token:
        await request.app.state.services.auth.logout(token)
    response.delete_cookie("sage_session")
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(current_user)):
    return {k: user[k] for k in ("id", "username", "role", "must_change_password")}


@router.post("/change-password")
async def change_password(body: ChangePassword, request: Request, user: dict = Depends(current_user)):
    try:
        await request.app.state.services.auth.change_password(user["id"], body.old, body.new, user["username"])
    except AuthError as e:
        raise HTTPException(400, e.code)
    return {"ok": True}
