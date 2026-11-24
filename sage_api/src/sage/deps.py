from fastapi import Depends, HTTPException, Request

_ALLOWED_WHEN_CHANGE_PENDING = ("/api/auth/me", "/api/auth/change-password", "/api/auth/logout")


async def current_user(request: Request) -> dict:
    token = request.cookies.get("sage_session")
    user = await request.app.state.services.auth.user_for_token(token) if token else None
    if not user:
        raise HTTPException(401, "not_authenticated")
    if user["must_change_password"] and request.url.path not in _ALLOWED_WHEN_CHANGE_PENDING:
        raise HTTPException(403, "password_change_required")
    return user


async def admin_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "admin_only")
    return user
