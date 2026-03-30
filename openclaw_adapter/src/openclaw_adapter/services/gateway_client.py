# -*- coding: utf-8 -*-
"""Gateway backends: stub and HTTP."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, Optional, Tuple

import httpx

from openclaw_adapter.config import get_settings
from openclaw_adapter.services.cron_payload import strip_adapter_meta_for_gateway

logger = logging.getLogger(__name__)


def _get_by_path(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _extract_job_id_from_tools_invoke_response(data: Dict[str, Any], path: str) -> Optional[str]:
    """
    OpenClaw POST /tools/invoke 成功时常见两种形态：
    1) {"ok":true,"result":{"jobId":"..."}} 或 path 可配置的嵌套
    2) {"ok":true,"result":{"content":[{"type":"text","text":"{ \"id\": \"...\", \"jobId\": \"...\" }"}]}}
       —— text 为 JSON 字符串，Cron 任务 id 多在 id / jobId
    """
    if not isinstance(data, dict):
        return None

    jid = _get_by_path(data, path)
    if jid is not None and str(jid).strip():
        return str(jid).strip()

    result = data.get("result")
    if isinstance(result, dict):
        for key in ("jobId", "id", "job_id"):
            v = result.get(key)
            if v is not None and str(v).strip():
                return str(v).strip()

        content = result.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "text":
                    continue
                raw = block.get("text")
                if not isinstance(raw, str) or not raw.strip():
                    continue
                try:
                    inner = json.loads(raw.strip())
                except json.JSONDecodeError:
                    continue
                if isinstance(inner, dict):
                    for key in ("jobId", "id", "job_id"):
                        v = inner.get(key)
                        if v is not None and str(v).strip():
                            return str(v).strip()

    for key in ("jobId", "id"):
        v = data.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


class GatewayClient:
    async def create_cron_job(self, cron_add_params: Dict[str, Any]) -> Tuple[str, Optional[str]]:
        """
        Returns (openclaw_task_id, error_message).
        """
        raise NotImplementedError

    async def remove_cron_job(self, gateway_job_id: str) -> Tuple[bool, Optional[str]]:
        raise NotImplementedError


class StubGatewayClient(GatewayClient):
    """No network; generates synthetic job id (dev / CI)."""

    async def create_cron_job(self, cron_add_params: Dict[str, Any]) -> Tuple[str, Optional[str]]:
        jid = f"stub-{uuid.uuid4().hex[:16]}"
        logger.info("StubGateway: would create job %s payload keys=%s", jid, list(cron_add_params.keys()))
        return jid, None

    async def remove_cron_job(self, gateway_job_id: str) -> Tuple[bool, Optional[str]]:
        logger.info("StubGateway: would remove job %s", gateway_job_id)
        return True, None


class HttpGatewayClient(GatewayClient):
    """
    POST configurable URL with body from template.
    Expects JSON response; extracts job id via gateway_http_job_id_path.
    """

    async def create_cron_job(self, cron_add_params: Dict[str, Any]) -> Tuple[str, Optional[str]]:
        settings = get_settings()
        url = settings.gateway_http_url
        if not url:
            return "", "ADAPTER_GATEWAY_HTTP_URL not set"

        clean = strip_adapter_meta_for_gateway(cron_add_params)
        body_inner = json.dumps(clean, ensure_ascii=False)
        tpl = settings.gateway_http_body_template
        try:
            raw_body = tpl.replace("{body}", body_inner)
        except Exception as e:
            return "", f"body template error: {e}"

        headers = {"Content-Type": "application/json"}
        if settings.gateway_http_token:
            headers["Authorization"] = f"Bearer {settings.gateway_http_token}"

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(url, content=raw_body.encode("utf-8"), headers=headers)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            logger.exception("Gateway HTTP error")
            return "", str(e)

        if isinstance(data, dict) and data.get("ok") is False:
            err = data.get("error")
            return "", str(err if err is not None else data)

        job_id = _extract_job_id_from_tools_invoke_response(data, settings.gateway_http_job_id_path)
        if not job_id:
            snippet = repr(data)
            if len(snippet) > 800:
                snippet = snippet[:800] + "..."
            return "", f"could not parse job id from response: {snippet}"
        logger.info("HttpGateway: parsed job id from tools/invoke: %s", job_id)
        return job_id, None

    async def remove_cron_job(self, gateway_job_id: str) -> Tuple[bool, Optional[str]]:
        settings = get_settings()
        remove_url = (settings.gateway_http_remove_url or "").strip()
        token = settings.gateway_http_token or ""
        auth_headers: Dict[str, str] = {}
        if token:
            auth_headers["Authorization"] = f"Bearer {token}"

        if remove_url:
            url = remove_url.replace("{job_id}", gateway_job_id)
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    r = await client.delete(url, headers=auth_headers)
                    r.raise_for_status()
                return True, None
            except Exception as e:
                return False, str(e)

        invoke_url = (settings.gateway_http_url or "").strip()
        if not invoke_url:
            logger.warning("gateway_http_remove_url unset and ADAPTER_GATEWAY_HTTP_URL empty; skip remote remove")
            return True, None

        path = invoke_url.rstrip("/").lower()
        if not path.endswith("/tools/invoke"):
            logger.warning(
                "gateway_http_remove_url unset and URL is not .../tools/invoke; skip remote remove "
                "(set ADAPTER_GATEWAY_HTTP_REMOVE_URL or point ADAPTER_GATEWAY_HTTP_URL at OpenClaw /tools/invoke)"
            )
            return True, None

        # 开源 OpenClaw：tool=cron + action=remove（与 action=list / action=add 同族）
        body = {"tool": "cron", "action": "remove", "args": {"jobId": gateway_job_id}}
        headers = {"Content-Type": "application/json", **auth_headers}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(invoke_url, json=body, headers=headers)
                r.raise_for_status()
                data = r.json()
            if isinstance(data, dict) and data.get("ok") is False:
                return False, str(data.get("error", data))
            return True, None
        except Exception as e:
            return False, str(e)


def get_gateway_client() -> GatewayClient:
    settings = get_settings()
    if settings.gateway_mode.lower() == "http":
        return HttpGatewayClient()
    return StubGatewayClient()
