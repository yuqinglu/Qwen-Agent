# -*- coding: utf-8 -*-
"""
Build OpenClaw Gateway cron.add compatible payloads.

See: https://docs.openclaw.ai/automation/cron-jobs
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from openclaw_adapter.constants import API_URL_PREFIX


def build_agent_message(task_description: str, original_message: str) -> str:
    parts = [f"【任务说明】{task_description.strip()}", f"【用户原话】{original_message.strip()}"]
    return "\n\n".join(parts)


def build_webhook_delivery(
    adapter_public_base_url: str,
    bearer_token: str,
) -> Dict[str, Any]:
    """
    delivery.mode webhook; OpenClaw posts finished payload to adapter.
    If bearer_token set, configure cron.webhookToken on Gateway side separately,
    or pass via URL query (less ideal). Official: Authorization Bearer when cron.webhookToken set.
    """
    url = f"{adapter_public_base_url.rstrip('/')}{API_URL_PREFIX}/internal/openclaw/webhook"
    return {
        "mode": "webhook",
        "to": url,
    }


def build_cron_add_body(
    *,
    name: str,
    task_type: str,
    schedule: Optional[str],
    schedule_timezone: Optional[str],
    task_description: str,
    original_message: str,
    adapter_public_base_url: str,
    webhook_bearer_token: str,
    client_task_id: str,
) -> Dict[str, Any]:
    """
    Returns the `params` object for cron.add (tool call), not the full RPC envelope.
    """
    tz = schedule_timezone or "Asia/Shanghai"
    message = build_agent_message(task_description, original_message)
    delivery = build_webhook_delivery(adapter_public_base_url, webhook_bearer_token)

    if task_type == "periodic":
        if not schedule:
            raise ValueError("periodic task requires schedule (cron expr)")
        schedule_obj: Dict[str, Any] = {
            "kind": "cron",
            "expr": schedule,
            "tz": tz,
        }
    else:
        # one_time / research: fire once soon (ISO UTC)
        at = (datetime.now(timezone.utc) + timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        schedule_obj = {"kind": "at", "at": at}

    body: Dict[str, Any] = {
        "name": name[:120] or f"ty-mem-{client_task_id[:8]}",
        "schedule": schedule_obj,
        "sessionTarget": "isolated",
        "wakeMode": "now",
        "payload": {
            "kind": "agentTurn",
            "message": message,
            "lightContext": True,
        },
        "delivery": delivery,
        "deleteAfterRun": task_type != "periodic",
    }

    return body


def strip_adapter_meta_for_gateway(body: Dict[str, Any]) -> Dict[str, Any]:
    """Remove non-OpenClaw keys before sending to Gateway."""
    return {k: v for k, v in body.items() if not str(k).startswith("_")}
