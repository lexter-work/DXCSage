from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from sage.deps import admin_user
from sage.schedules import ScheduleError

router = APIRouter(prefix="/api/schedules")


class ScheduleIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    workflow: str
    input: dict = Field(default_factory=dict)
    kind: Literal["interval", "daily"]
    interval_minutes: int | None = None
    at_time: str | None = None
    enabled: bool = True


class Enabled(BaseModel):
    enabled: bool


def _svc(request):
    return request.app.state.services


async def _save(request, schedule_id, body: ScheduleIn, admin):
    try:
        return await _svc(request).schedules.save(schedule_id, actor=admin, **body.model_dump())
    except ScheduleError as e:
        raise HTTPException(400, str(e))


@router.get("")
async def list_schedules(request: Request, admin: dict = Depends(admin_user)):
    return await _svc(request).schedules.items()


@router.post("")
async def create(body: ScheduleIn, request: Request, admin: dict = Depends(admin_user)):
    return await _svc(request).schedules.get(await _save(request, None, body, admin))


@router.put("/{schedule_id}")
async def update(schedule_id: int, body: ScheduleIn, request: Request, admin: dict = Depends(admin_user)):
    svc = _svc(request)
    if not await svc.schedules.get(schedule_id):
        raise HTTPException(404, "not_found")
    await _save(request, schedule_id, body, admin)
    return await svc.schedules.get(schedule_id)


@router.post("/{schedule_id}/enabled")
async def enabled(schedule_id: int, body: Enabled, request: Request, admin: dict = Depends(admin_user)):
    svc = _svc(request)
    if not await svc.schedules.get(schedule_id):
        raise HTTPException(404, "not_found")
    await svc.schedules.set_enabled(schedule_id, body.enabled, admin["username"])
    return await svc.schedules.get(schedule_id)


@router.post("/{schedule_id}/run")
async def run_now(schedule_id: int, request: Request, admin: dict = Depends(admin_user)):
    """Start one run now. The timetable is not moved."""
    svc = _svc(request)
    s = await svc.schedules.get(schedule_id)
    if not s:
        raise HTTPException(404, "not_found")
    run_id = await svc.agent.run_schedule(s, advance=False)
    if run_id is None:
        raise HTTPException(409, "The previous run of this schedule is still going.")
    return {"run_id": run_id}


@router.delete("/{schedule_id}")
async def delete(schedule_id: int, request: Request, admin: dict = Depends(admin_user)):
    await _svc(request).schedules.delete(schedule_id, admin["username"])
    return {"ok": True}
