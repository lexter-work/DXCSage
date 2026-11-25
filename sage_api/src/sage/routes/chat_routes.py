import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from sage.deps import current_user
from sage.util import iso

router = APIRouter(prefix="/api")


class NewChat(BaseModel):
    title: str = "New chat"
    provider: str
    model: str


class ChatPatch(BaseModel):
    title: str | None = None
    provider: str | None = None
    model: str | None = None


class Text(BaseModel):
    text: str


def _svc(request):
    return request.app.state.services


async def _check_model(svc, provider, model):
    models = await svc.settings.get("providers.models")
    if provider not in models or model not in models[provider]:
        raise HTTPException(400, "model_not_allowed")
    if not await svc.settings.get(f"providers.{provider}_api_key"):
        raise HTTPException(400, "provider_not_configured")


async def _own_chat(svc, chat_id, user):
    chat = await svc.db.fetchone("SELECT * FROM chats WHERE id=? AND user_id=? AND deleted_at IS NULL", (chat_id, user["id"]))
    if not chat:
        raise HTTPException(404, "chat_not_found")
    return chat


@router.get("/providers")
async def providers(request: Request, user: dict = Depends(current_user)):
    svc = _svc(request)
    models = await svc.settings.get("providers.models")
    return {p: m for p, m in models.items() if await svc.settings.get(f"providers.{p}_api_key")}


@router.get("/chats")
async def list_chats(request: Request, user: dict = Depends(current_user)):
    return await _svc(request).db.fetchall(
        "SELECT c.id,c.title,c.provider,c.model,c.created_at,"
        "(SELECT status FROM runs r WHERE r.chat_id=c.id ORDER BY r.id DESC LIMIT 1) AS last_run_status,"
        "(SELECT id FROM runs r WHERE r.chat_id=c.id ORDER BY r.id DESC LIMIT 1) AS last_run_id "
        "FROM chats c WHERE c.user_id=? AND c.deleted_at IS NULL AND c.provider<>'schedule' ORDER BY c.id DESC", (user["id"],))


@router.post("/chats")
async def create_chat(body: NewChat, request: Request, user: dict = Depends(current_user)):
    svc = _svc(request)
    await _check_model(svc, body.provider, body.model)
    cid = await svc.db.execute("INSERT INTO chats(user_id,title,provider,model,created_at) VALUES(?,?,?,?,?)",
                               (user["id"], body.title, body.provider, body.model, iso(svc.clock())))
    await svc.audit.write("chat.create", user["username"], detail={"chat_id": cid})
    return {"id": cid}


@router.patch("/chats/{chat_id}")
async def patch_chat(chat_id: int, body: ChatPatch, request: Request, user: dict = Depends(current_user)):
    svc = _svc(request)
    chat = await _own_chat(svc, chat_id, user)
    provider, model = body.provider or chat["provider"], body.model or chat["model"]
    if body.provider or body.model:
        await _check_model(svc, provider, model)
    await svc.db.execute("UPDATE chats SET title=?, provider=?, model=? WHERE id=?",
                         (body.title or chat["title"], provider, model, chat_id))
    return {"ok": True}


@router.delete("/chats/{chat_id}")
async def delete_chat(chat_id: int, request: Request, user: dict = Depends(current_user)):
    svc = _svc(request)
    await _own_chat(svc, chat_id, user)
    await svc.db.execute("UPDATE chats SET deleted_at=? WHERE id=?", (iso(svc.clock()), chat_id))
    await svc.audit.write("chat.delete", user["username"], detail={"chat_id": chat_id})
    return {"ok": True}


@router.get("/chats/{chat_id}/messages")
async def messages(chat_id: int, request: Request, user: dict = Depends(current_user)):
    svc = _svc(request)
    await _own_chat(svc, chat_id, user)
    return await svc.db.fetchall("SELECT id,run_id,role,content,created_at FROM messages WHERE chat_id=? ORDER BY id", (chat_id,))


@router.post("/chats/{chat_id}/runs")
async def start_run(chat_id: int, body: Text, request: Request, user: dict = Depends(current_user)):
    svc = _svc(request)
    try:
        run_id = await svc.agent.create_run(chat_id, user, body.text)
    except LookupError:
        raise HTTPException(404, "chat_not_found")
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    if not svc.manual_drive:
        svc.agent.launch(run_id)
    return {"run_id": run_id}


async def _own_run(svc, run_id, user):
    run = await svc.db.fetchone("SELECT * FROM runs WHERE id=?", (run_id,))
    if not run or (run["user_id"] != user["id"] and user["role"] != "admin"):
        raise HTTPException(404, "run_not_found")
    return run


@router.get("/runs/{run_id}")
async def run_info(run_id: int, request: Request, user: dict = Depends(current_user)):
    """Own-run summary for the chat: status, timing, tokens, and the steps of each workflow call (no inputs or outputs)."""
    svc = _svc(request)
    run = await _own_run(svc, run_id, user)
    calls = await svc.db.fetchall(
        "SELECT id,provider_call_id,workflow,system_id,status,started_at,ended_at FROM tool_calls WHERE run_id=? ORDER BY id", (run_id,))
    for c in calls:
        c["steps"] = await svc.db.fetchall(
            "SELECT seq,kind,attempt,name,status,created_at FROM tool_steps WHERE tool_call_id=? AND kind IN ('task','poll') ORDER BY seq,attempt",
            (c["id"],))
        sys_ = await svc.systems.get(c["system_id"]) if c["system_id"] else None
        c["system"] = {"label": sys_["label"], "sid": sys_["sid"], "client": sys_["client"]} if sys_ else None
    keep = ("id", "status", "started_at", "ended_at", "resume_at", "tokens_in", "tokens_out", "error")
    return {"run": {k: run[k] for k in keep}, "tool_calls": calls}


@router.post("/runs/{run_id}/cancel")
async def cancel(run_id: int, request: Request, user: dict = Depends(current_user)):
    svc = _svc(request)
    await _own_run(svc, run_id, user)
    await svc.agent.cancel(run_id, user["username"])
    return {"ok": True}


@router.get("/runs/{run_id}/events")
async def events(run_id: int, request: Request, after: int = 0, user: dict = Depends(current_user)):
    svc = _svc(request)
    await _own_run(svc, run_id, user)

    async def gen():
        last, idle = after, 0
        while True:
            rows = await svc.db.fetchall("SELECT id,type,data,created_at FROM run_events WHERE run_id=? AND id>? ORDER BY id", (run_id, last))
            for r in rows:
                last, idle = r["id"], 0
                yield f"id: {r['id']}\ndata: {json.dumps({'type': r['type'], 'data': json.loads(r['data']), 'ts': r['created_at']})}\n\n"
            run = await svc.db.fetchone("SELECT status FROM runs WHERE id=?", (run_id,))
            if not rows and run["status"] in ("done", "failed", "cancelled"):
                return
            if await request.is_disconnected():
                return
            idle += 1
            if idle % 50 == 0:
                yield ": ping\n\n"
            await asyncio.sleep(0.3)
    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/usage/me")
async def usage_me(request: Request, user: dict = Depends(current_user)):
    return await _svc(request).usage.me(user["id"])
