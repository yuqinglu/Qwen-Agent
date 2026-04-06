# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw_adapter.api.deps import verify_adapter_api_key
from openclaw_adapter.api.schemas import TaskCreateRequest, TaskCreateResponse, TaskStatusResponse
from openclaw_adapter.config import get_settings
from openclaw_adapter.db.database import get_db
from openclaw_adapter.services import task_service

router = APIRouter(tags=["tasks"])


@router.post("/tasks", response_model=TaskCreateResponse)
async def create_task(
    body: TaskCreateRequest,
    _: None = Depends(verify_adapter_api_key),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    row, err = await task_service.create_task(
        db,
        client_task_id=body.client_task_id,
        user_id=body.user_id,
        task_description=body.task_description,
        original_message=body.original_message,
        callback_url=body.callback_url,
        task_type=body.task_type,
        schedule=body.schedule,
        schedule_timezone=body.schedule_timezone,
        fallback_reason=body.fallback_reason,
        context=body.context,
        adapter_public_base_url=settings.adapter_public_base_url,
        webhook_bearer_token=settings.openclaw_webhook_bearer_token,
    )
    if err:
        raise HTTPException(status_code=400, detail=err)
    return TaskCreateResponse(
        openclaw_task_id=row.openclaw_task_id,
        client_task_id=row.client_task_id,
        status="accepted",
    )


@router.get("/tasks/{openclaw_task_id}", response_model=TaskStatusResponse)
async def get_task(
    openclaw_task_id: str,
    _: None = Depends(verify_adapter_api_key),
    db: AsyncSession = Depends(get_db),
):
    row = await task_service.get_task_by_openclaw_id(db, openclaw_task_id)
    if not row:
        raise HTTPException(status_code=404, detail="task not found")
    return TaskStatusResponse(
        openclaw_task_id=row.openclaw_task_id,
        client_task_id=row.client_task_id,
        status=row.status,
        task_type=row.task_type,
        created_at=row.created_at.isoformat() if row.created_at else None,
        next_run_at=row.next_run_at,
        result_summary=row.last_result_preview,
    )


@router.delete("/tasks/{openclaw_task_id}")
async def delete_task(
    openclaw_task_id: str,
    _: None = Depends(verify_adapter_api_key),
    db: AsyncSession = Depends(get_db),
):
    row = await task_service.get_task_by_openclaw_id(db, openclaw_task_id)
    if not row:
        raise HTTPException(status_code=404, detail="task not found")
    ok, msg = await task_service.cancel_task(db, openclaw_task_id)
    if not ok:
        raise HTTPException(status_code=404, detail=msg)
    return {
        "openclaw_task_id": openclaw_task_id,
        "client_task_id": row.client_task_id,
        "status": "cancelled",
        "message": msg,
    }
