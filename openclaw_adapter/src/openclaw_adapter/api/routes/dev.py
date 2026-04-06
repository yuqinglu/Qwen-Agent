# -*- coding: utf-8 -*-
"""Local testing only (stub gateway)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from openclaw_adapter.api.deps import verify_adapter_api_key
from openclaw_adapter.config import get_settings

router = APIRouter(prefix="/internal/dev", tags=["dev"])


class SimulateCallbackBody(BaseModel):
    openclaw_task_id: str = Field(..., description="Adapter openclaw_task_id / stub job id")
    status: str = Field(default="done", description="done | failed")
    result: str | None = None
    error_message: str | None = None
    next_run_at: str | None = None


@router.post("/simulate-callback")
async def simulate_callback(
    body: SimulateCallbackBody,
    _: None = Depends(verify_adapter_api_key),
):
    settings = get_settings()
    if not settings.dev_endpoints_enabled:
        raise HTTPException(status_code=404, detail="dev endpoints disabled")
    from openclaw_adapter.db.database import get_session_factory
    from openclaw_adapter.services.webhook_forwarder import forward_with_retries
    from sqlalchemy import select

    from openclaw_adapter.db.models import AdapterTask

    factory = get_session_factory()
    async with factory() as session:
        row = await session.scalar(
            select(AdapterTask).where(AdapterTask.openclaw_task_id == body.openclaw_task_id)
        )
        if not row:
            raise HTTPException(status_code=404, detail="task not found")
        url = row.callback_url
        payload = {
            "task_id": row.openclaw_task_id,
            "client_task_id": row.client_task_id,
            "status": body.status,
            "result": body.result if body.status == "done" else None,
            "error_message": body.error_message if body.status == "failed" else None,
            "next_run_at": body.next_run_at,
            "executed_at": None,
        }

    await forward_with_retries(url, payload, secret=settings.ty_mem_callback_hmac_secret)

    # 与真实入站一致：便于 GET /openclaw-adapter/v1/tasks/{id} 联调时看到 result_summary（此前仅转发 ty-mem，未写库）
    preview = (body.result or body.error_message or "")[:2000]
    async with factory() as session:
        row2 = await session.scalar(
            select(AdapterTask).where(AdapterTask.openclaw_task_id == body.openclaw_task_id)
        )
        if row2:
            row2.last_result_preview = preview
            if body.next_run_at:
                row2.next_run_at = body.next_run_at
            await session.commit()

    return {"ok": True, "forwarded": True}
