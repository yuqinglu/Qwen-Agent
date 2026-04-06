# -*- coding: utf-8 -*-
"""Sign and POST callback to ty-mem-agent."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, Optional

import httpx

from openclaw_adapter.config import get_settings

logger = logging.getLogger(__name__)


def sign_body(body_bytes: bytes, secret: str) -> tuple[str, str]:
    ts = str(int(time.time()))
    msg = ts.encode() + b"." + body_bytes
    sig = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return ts, sig


async def forward_to_ty_mem_agent(
    callback_url: str,
    payload: Dict[str, Any],
    *,
    secret: str,
    timeout: float = 30.0,
) -> tuple[bool, str]:
    """
    POST JSON to ty-mem-agent with X-OpenClaw-Timestamp and X-OpenClaw-Signature.
    """
    body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if not secret:
        logger.warning("TY_MEM_CALLBACK_HMAC_SECRET empty; sending unsigned (ty-mem may reject)")
        headers = {"Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(callback_url, content=body_bytes, headers=headers)
        return r.is_success, r.text[:500]

    ts, sig = sign_body(body_bytes, secret)
    headers = {
        "Content-Type": "application/json",
        "X-OpenClaw-Timestamp": ts,
        "X-OpenClaw-Signature": sig,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(callback_url, content=body_bytes, headers=headers)
    if not r.is_success:
        logger.warning("Callback failed: %s %s", r.status_code, r.text[:300])
    return r.is_success, r.text[:500]


async def forward_with_retries(
    callback_url: str,
    payload: Dict[str, Any],
    *,
    secret: str,
) -> None:
    delays = [0, 30, 120, 600]
    settings = get_settings()
    secret = secret or settings.ty_mem_callback_hmac_secret
    for i, d in enumerate(delays):
        if d:
            await __import__("asyncio").sleep(d)
        ok, _ = await forward_to_ty_mem_agent(callback_url, payload, secret=secret)
        if ok:
            return
        logger.warning("Callback attempt %s failed", i + 1)
