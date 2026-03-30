# -*- coding: utf-8 -*-
"""Inbound webhook from OpenClaw Gateway (delivery.mode=webhook)."""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from openclaw_adapter.config import get_settings
from openclaw_adapter.db.database import get_session_factory
from openclaw_adapter.services.inbound_parse import (
    extract_job_id,
    extract_next_run_at,
    extract_result_text,
    extract_status_ok,
)
from openclaw_adapter.services.webhook_forwarder import forward_with_retries

logger = logging.getLogger(__name__)

router = APIRouter(tags=["inbound"])


async def _process_inbound(body: Dict[str, Any]) -> None:
    settings = get_settings()
    logger.info("OpenClaw inbound webhook: top-level keys=%s", list(body.keys())[:40])
    job_id = extract_job_id(body)
    if not job_id:
        logger.warning("Inbound webhook: no job id in payload keys=%s", list(body.keys())[:20])
        return

    text = extract_result_text(body)
    ok = extract_status_ok(body)
    next_run = extract_next_run_at(body)

    factory = get_session_factory()
    async with factory() as session:
        from sqlalchemy import select

        from openclaw_adapter.db.models import AdapterTask

        row = await session.scalar(
            select(AdapterTask).where(
                (AdapterTask.gateway_job_id == job_id) | (AdapterTask.openclaw_task_id == job_id)
            )
        )
        if not row:
            logger.warning("Inbound webhook: no adapter task for job_id=%s", job_id)
            return

        row.last_result_preview = (text or "")[:2000]
        if next_run:
            row.next_run_at = next_run
        await session.commit()

        callback_url = row.callback_url
        payload = {
            "task_id": row.openclaw_task_id,
            "client_task_id": row.client_task_id,
            "status": "done" if ok else "failed",
            "result": text if ok else None,
            "error_message": None if ok else (text or "execution failed"),
            "next_run_at": next_run,
            "executed_at": None,
        }

    await forward_with_retries(callback_url, payload, secret=settings.ty_mem_callback_hmac_secret)


@router.post("/internal/openclaw/webhook")
async def openclaw_inbound(request: Request, background_tasks: BackgroundTasks):
    settings = get_settings()
    if settings.openclaw_webhook_bearer_token:
        auth = request.headers.get("authorization") or ""
        expected = f"Bearer {settings.openclaw_webhook_bearer_token}"
        if auth != expected:
            raise HTTPException(status_code=401, detail="invalid webhook authorization")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="json object expected")

    background_tasks.add_task(_process_inbound, body)
    return {"ok": True, "accepted": True}
