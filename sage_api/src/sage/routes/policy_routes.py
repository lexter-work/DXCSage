from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from sage.deps import admin_user
from sage.policies import MAX_TEXT, PolicyError, extract_text

router = APIRouter(prefix="/api/policies")


class PolicyIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    required: bool = False


def _svc(request):
    return request.app.state.services.policies


async def _guard(coro):
    try:
        return await coro
    except PolicyError as e:
        raise HTTPException(400, str(e))


@router.get("")
async def items(request: Request, admin: dict = Depends(admin_user)):
    return await _svc(request).items()


@router.post("")
async def create(body: PolicyIn, request: Request, admin: dict = Depends(admin_user)):
    await _guard(_svc(request).save(None, body.name, body.text, body.required, admin["username"]))
    return await _svc(request).items()


@router.put("/extract")
async def extract(filename: str, request: Request, admin: dict = Depends(admin_user)):
    """The raw bytes of a .txt, .md or .docx file are the body. Returns its text, so the admin can check it before saving."""
    data = await request.body()
    if not data or len(data) > 2_000_000:
        raise HTTPException(400, "The file must be between 1 byte and 2 MB.")
    try:
        return {"text": extract_text(filename, data)[:MAX_TEXT]}
    except PolicyError as e:
        raise HTTPException(400, str(e))


@router.put("/{policy_id}")
async def update(policy_id: int, body: PolicyIn, request: Request, admin: dict = Depends(admin_user)):
    await _guard(_svc(request).save(policy_id, body.name, body.text, body.required, admin["username"]))
    return await _svc(request).items()


@router.get("/{policy_id}/reviews")
async def reviews(policy_id: int, request: Request, admin: dict = Depends(admin_user)):
    return await _svc(request).reviews(policy_id)


@router.post("/{policy_id}/clear-reviews")
async def clear(policy_id: int, request: Request, admin: dict = Depends(admin_user)):
    await _svc(request).clear_reviews(policy_id, admin["username"])
    return {"ok": True}


@router.delete("/{policy_id}")
async def delete(policy_id: int, request: Request, admin: dict = Depends(admin_user)):
    await _svc(request).delete(policy_id, admin["username"])
    return {"ok": True}
