# -*- coding: utf-8 -*-
"""
OpenClaw 集成 HTTP 客户端（对端默认为「适配层 Adapter Service」）

ty-mem-agent 不直连 OpenClaw Gateway；OPENCLAW_API_BASE 应指向适配层 REST 根（含 /openclaw-adapter/v1）
（见 ty_mem_agent/doc/OPENCLAW_ADAPTOR_SERVICE.md）。适配层负责调用 Gateway Cron/agentTurn、
接收 OpenClaw delivery.webhook，再带 HMAC 回调本服务的
`/agent/api/v1/chat/openclaw/callback`（相对 `OPENCLAW_CALLBACK_BASE_URL`）。

verify_openclaw_signature：验证的是「适配层转发给 ty-mem-agent」的请求，不是 Gateway 原始 webhook。

任务提交 payload 与 OPENCLAW_INTEGRATION_GUIDE.md 一致，字段示例：
    client_task_id, user_id, task_description, original_message, callback_url,
    task_type, schedule, schedule_timezone, fallback_reason, context
"""

import hashlib
import hmac
import json
import time
import uuid
from typing import Any, Dict, Optional

import httpx
from loguru import logger


# ---------------------------------------------------------------------------
# 配置加载（延迟，避免循环导入）
# ---------------------------------------------------------------------------

def _get_settings():
    from ty_mem_agent.config.settings import settings
    return settings


# ---------------------------------------------------------------------------
# HMAC 签名工具（用于验证 OpenClaw 回调请求）
# ---------------------------------------------------------------------------

def verify_callback_timestamp(timestamp: str, max_skew_seconds: int = 300) -> bool:
    """
    防重放：时间戳与当前时间相差超过 max_skew_seconds 则拒绝。
    """
    if not timestamp or not str(timestamp).strip().isdigit():
        return False
    try:
        ts = int(timestamp)
        now = int(time.time())
        return abs(now - ts) <= max_skew_seconds
    except Exception:
        return False


def verify_openclaw_signature(
    body: bytes,
    timestamp: str,
    signature: str,
    secret: Optional[str] = None,
) -> bool:
    """
    验证回调请求的 HMAC-SHA256 签名（由适配层在转发 ty-mem-agent 时生成）。

    请求头约定：
      X-OpenClaw-Timestamp: <unix_timestamp>
      X-OpenClaw-Signature: <hmac_hex>

    签名算法：HMAC-SHA256(key=secret, msg=timestamp + "." + body_bytes)

    Args:
        body: 原始请求体字节
        timestamp: 请求头中的时间戳字符串
        signature: 请求头中的签名
        secret: HMAC 密钥，默认从配置读取

    Returns:
        bool — 签名是否合法
    """
    if secret is None:
        secret = _get_settings().OPENCLAW_CALLBACK_SECRET or ""

    if not secret:
        logger.warning("[OpenClawClient] OPENCLAW_CALLBACK_SECRET 未配置，跳过签名验证")
        return True

    try:
        msg = timestamp.encode() + b"." + body
        expected = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception as e:
        logger.error(f"[OpenClawClient] 签名验证异常: {e}")
        return False


def generate_outbound_signature(body: bytes, secret: str) -> tuple[str, str]:
    """
    为向 OpenClaw 发起的请求生成签名（如需双向验证）。
    返回 (timestamp_str, signature_hex)
    """
    timestamp = str(int(time.time()))
    msg = timestamp.encode() + b"." + body
    sig = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return timestamp, sig


# ---------------------------------------------------------------------------
# OpenClaw HTTP 客户端
# ---------------------------------------------------------------------------

class OpenClawClient:
    """
    OpenClaw 服务的 HTTP 客户端。
    使用 httpx 异步客户端，支持超时与重试。
    """

    def __init__(self):
        settings = _get_settings()
        self._api_base = (settings.OPENCLAW_API_BASE or "").rstrip("/")
        self._api_key = settings.OPENCLAW_API_KEY or ""
        self._callback_base = (settings.OPENCLAW_CALLBACK_BASE_URL or "").rstrip("/")
        self._timeout = httpx.Timeout(30.0)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Client": "ty-mem-agent",
        }

    def _callback_url(self) -> str:
        # 与 general_chat_routes 中 prefix=/agent/api/v1/chat + /openclaw/callback 一致
        return f"{self._callback_base}/agent/api/v1/chat/openclaw/callback"

    def _is_configured(self) -> bool:
        s = _get_settings()
        if not getattr(s, "OPENCLAW_ENABLED", True):
            return False
        return bool(self._api_base and self._api_key)

    # ------------------------------------------------------------------
    # 任务提交
    # ------------------------------------------------------------------

    async def submit_task(
        self,
        task_id: str,
        user_id: int,
        task_description: str,
        original_message: str,
        task_type: str = "one_time",
        schedule: Optional[str] = None,
        fallback_reason: Optional[str] = None,
        session_id: Optional[str] = None,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        向 OpenClaw 提交任务。

        Returns:
            {"success": bool, "openclaw_task_id": str | None, "message": str}
        """
        if not self._is_configured():
            s = _get_settings()
            if not getattr(s, "OPENCLAW_ENABLED", True):
                logger.debug("[OpenClawClient] OPENCLAW_ENABLED=false，跳过提交")
                return {
                    "success": False,
                    "openclaw_task_id": None,
                    "message": "OpenClaw 已关闭",
                }
            logger.warning("[OpenClawClient] OpenClaw 未配置，任务提交被跳过（本地 mock）")
            return {
                "success": False,
                "openclaw_task_id": None,
                "message": "OpenClaw 未配置",
            }

        payload = {
            "client_task_id": task_id,
            "user_id": str(user_id),
            "task_description": task_description,
            "original_message": original_message,
            "callback_url": self._callback_url(),
            "task_type": task_type,
            "schedule": schedule,
            "schedule_timezone": "Asia/Shanghai",
            "fallback_reason": fallback_reason or "unknown",
            "context": {
                "session_id": session_id,
                "calendar_user_id": user_id,
                **(extra_context or {}),
            },
        }

        url = f"{self._api_base}/tasks"
        logger.info(
            f"[OpenClawClient] 提交任务: client_task_id={task_id}, type={task_type}, "
            f"schedule={schedule}, user_id={user_id}"
        )

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload, headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
                # 优先取 openclaw_task_id，兼容旧字段名 task_id/id
                openclaw_task_id = data.get("openclaw_task_id") or data.get("task_id") or data.get("id") or task_id
                logger.info(f"[OpenClawClient] 任务提交成功: openclaw_task_id={openclaw_task_id}")
                return {
                    "success": True,
                    "openclaw_task_id": openclaw_task_id,
                    "message": "提交成功",
                    "raw": data,
                }
        except httpx.HTTPStatusError as e:
            logger.error(f"[OpenClawClient] 任务提交 HTTP 错误: {e.response.status_code} {e.response.text}")
            return {
                "success": False,
                "openclaw_task_id": None,
                "message": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            }
        except Exception as e:
            logger.error(f"[OpenClawClient] 任务提交异常: {e}")
            return {
                "success": False,
                "openclaw_task_id": None,
                "message": str(e),
            }

    # ------------------------------------------------------------------
    # 任务状态查询
    # ------------------------------------------------------------------

    async def get_task(self, openclaw_task_id: str) -> Dict[str, Any]:
        """
        查询 OpenClaw 任务状态。

        Returns:
            {"success": bool, "status": str, "result": Any, ...}
        """
        if not self._is_configured():
            return {"success": False, "message": "OpenClaw 未配置"}

        url = f"{self._api_base}/tasks/{openclaw_task_id}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url, headers=self._headers())
                resp.raise_for_status()
                return {"success": True, **resp.json()}
        except Exception as e:
            logger.error(f"[OpenClawClient] 查询任务失败: {e}")
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------
    # 取消任务
    # ------------------------------------------------------------------

    async def cancel_task(self, openclaw_task_id: str) -> Dict[str, Any]:
        """
        取消 OpenClaw 任务（停止定期执行或取消待执行的一次性任务）。
        """
        if not self._is_configured():
            return {"success": False, "message": "OpenClaw 未配置"}

        url = f"{self._api_base}/tasks/{openclaw_task_id}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.delete(url, headers=self._headers())
                resp.raise_for_status()
                logger.info(f"[OpenClawClient] 任务已取消: openclaw_task_id={openclaw_task_id}")
                return {"success": True, "message": "已取消"}
        except Exception as e:
            logger.error(f"[OpenClawClient] 取消任务失败: {e}")
            return {"success": False, "message": str(e)}


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------

_client: Optional[OpenClawClient] = None


def get_openclaw_client() -> OpenClawClient:
    """获取 OpenClawClient 单例。"""
    global _client
    if _client is None:
        _client = OpenClawClient()
    return _client
