import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from sage.deps import admin_user

router = APIRouter(prefix="/api")


class SettingBody(BaseModel):
    key: str
    value: object


def _svc(request):
    return request.app.state.services


@router.get("/settings")
async def get_settings(request: Request, admin: dict = Depends(admin_user)):
    return await _svc(request).settings.public()


@router.put("/settings")
async def put_setting(body: SettingBody, request: Request, admin: dict = Depends(admin_user)):
    try:
        await _svc(request).settings.set(body.key, body.value, admin["username"])
    except KeyError:
        raise HTTPException(400, "unknown_setting")
    return {"ok": True}


@router.get("/usage")
async def usage_all(request: Request, admin: dict = Depends(admin_user)):
    return await _svc(request).usage.all()


@router.get("/runs")
async def runs(request: Request, user_id: int | None = None, status: str | None = None, limit: int = 100, offset: int = 0,
               admin: dict = Depends(admin_user)):
    where, args = [], []
    if user_id is not None:
        where.append("r.user_id=?"); args.append(user_id)
    if status:
        where.append("r.status=?"); args.append(status)
    sql = ("SELECT r.*, u.username, c.title, (c.deleted_at IS NOT NULL) AS chat_deleted FROM runs r "
           "JOIN users u ON u.id=r.user_id JOIN chats c ON c.id=r.chat_id "
           + ("WHERE " + " AND ".join(where) if where else "") + " ORDER BY r.id DESC LIMIT ? OFFSET ?")
    rows = await _svc(request).db.fetchall(sql, (*args, min(limit, 500), offset))
    for r in rows:
        r["chat_deleted"] = bool(r["chat_deleted"])
    return rows


@router.get("/runs/{run_id}/detail")
async def run_detail(run_id: int, request: Request, admin: dict = Depends(admin_user)):
    db = _svc(request).db
    run = await db.fetchone("SELECT * FROM runs WHERE id=?", (run_id,))
    if not run:
        raise HTTPException(404, "run_not_found")
    calls = await db.fetchall("SELECT * FROM tool_calls WHERE run_id=? ORDER BY id", (run_id,))
    for c in calls:
        c["steps"] = await db.fetchall("SELECT * FROM tool_steps WHERE tool_call_id=? ORDER BY seq, attempt", (c["id"],))
    return {"run": run, "tool_calls": calls}


@router.get("/audit")
async def audit_list(request: Request, event: str | None = None, actor: str | None = None, limit: int = 200, offset: int = 0,
                     admin: dict = Depends(admin_user)):
    where, args = [], []
    if event:
        where.append("event=?"); args.append(event)
    if actor:
        where.append("actor=?"); args.append(actor)
    sql = "SELECT * FROM audit_log " + ("WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ? OFFSET ?"
    return await _svc(request).db.fetchall(sql, (*args, min(limit, 1000), offset))


@router.get("/audit/export.csv")
async def audit_csv(request: Request, admin: dict = Depends(admin_user)):
    rows = await _svc(request).db.fetchall("SELECT id,ts,event,actor,run_id,detail FROM audit_log ORDER BY id")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "ts", "event", "actor", "run_id", "detail"])
    for r in rows:
        w.writerow([r["id"], r["ts"], r["event"], r["actor"], r["run_id"], r["detail"]])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv")


@router.post("/audit/verify")
async def audit_verify(request: Request, admin: dict = Depends(admin_user)):
    ok, bad = await _svc(request).audit.verify()
    return {"ok": ok, "bad_id": bad}
