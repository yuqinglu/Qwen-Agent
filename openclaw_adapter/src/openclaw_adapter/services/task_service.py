# -*- coding: utf-8 -*-
"""Task lifecycle: create, get, cancel."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw_adapter.db.models import AdapterTask
from openclaw_adapter.services.cron_payload import build_cron_add_body, strip_adapter_meta_for_gateway
from openclaw_adapter.services.gateway_client import get_gateway_client

logger = logging.getLogger(__name__)


async def create_task(
    session: AsyncSession,
    *,
    client_task_id: str,
    user_id: str,
    task_description: str,
    original_message: str,
    callback_url: str,
    task_type: str,
    schedule: Optional[str],
    schedule_timezone: Optional[str],
    fallback_reason: str,
    context: Optional[Dict[str, Any]],
    adapter_public_base_url: str,
    webhook_bearer_token: str,
) -> Tuple[AdapterTask, Optional[str]]:
    """
    Idempotent on client_task_id: returns existing row if present.
    Returns (task, error_message).
    """
    existing = await session.scalar(
        select(AdapterTask).where(AdapterTask.client_task_id == client_task_id)
    )
    if existing:
        return existing, None

    try:
        cron_params = build_cron_add_body(
            name=f"ty-mem-{client_task_id[:12]}",
            task_type=task_type,
            schedule=schedule,
            schedule_timezone=schedule_timezone,
            task_description=task_description,
            original_message=original_message,
            adapter_public_base_url=adapter_public_base_url,
            webhook_bearer_token=webhook_bearer_token,
            client_task_id=client_task_id,
        )
    except ValueError as e:
        return None, str(e)

    gw = get_gateway_client()
    openclaw_task_id, err = await gw.create_cron_job(strip_adapter_meta_for_gateway(cron_params))
    if err:
        return None, err

    row = AdapterTask(
        client_task_id=client_task_id,
        openclaw_task_id=openclaw_task_id,
        gateway_job_id=openclaw_task_id,
        user_id=user_id,
        callback_url=callback_url,
        task_type=task_type,
        schedule=schedule,
        schedule_timezone=schedule_timezone,
        task_description=task_description,
        original_message=original_message,
        fallback_reason=fallback_reason or "unknown",
        context=context,
        status="accepted",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    logger.info("Created task client_task_id=%s openclaw_task_id=%s", client_task_id, openclaw_task_id)
    return row, None


async def get_task_by_openclaw_id(session: AsyncSession, openclaw_task_id: str) -> Optional[AdapterTask]:
    return await session.scalar(
        select(AdapterTask).where(AdapterTask.openclaw_task_id == openclaw_task_id)
    )


async def cancel_task(session: AsyncSession, openclaw_task_id: str) -> Tuple[bool, str]:
    row = await get_task_by_openclaw_id(session, openclaw_task_id)
    if not row:
        return False, "not found"
    if row.status == "cancelled":
        return True, "already cancelled"
    gw = get_gateway_client()
    gid = row.gateway_job_id or row.openclaw_task_id
    ok, err = await gw.remove_cron_job(gid)
    if not ok and err:
        logger.warning("Gateway remove failed: %s", err)
    row.status = "cancelled"
    await session.commit()
    return True, "cancelled"
