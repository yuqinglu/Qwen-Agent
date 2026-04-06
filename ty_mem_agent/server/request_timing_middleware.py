#!/usr/bin/env python3
"""
HTTP 请求耗时中间件：进入应用时打一条日志，返回前再打一条含耗时（毫秒）。
客户端总耗时 − 日志中的 app 耗时 ≈ 网络 / Nginx / TLS 等开销（粗略）。
"""

import time
from typing import Awaitable, Callable, Optional, Tuple

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """记录每个 HTTP 请求的进入时间与在应用内（含路由与后续中间件链）的耗时。"""

    def __init__(
        self,
        app,
        *,
        log_prefix: str = "⏱",
        skip_paths: Optional[Tuple[str, ...]] = None,
    ):
        super().__init__(app)
        self._log_prefix = log_prefix
        self._skip_paths = frozenset(skip_paths or ())

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if path in self._skip_paths:
            return await call_next(request)

        method = request.method
        qs = request.url.query
        path_for_log = f"{path}?{qs}" if qs else path
        user_hint = (
            request.headers.get("x-user-id")
            or request.headers.get("X-User-Id")
            or "-"
        )

        logger.info(
            f"{self._log_prefix} HTTP ← {method} {path_for_log} "
            f"x-user-id={user_hint} (entered app)"
        )
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.exception(
                f"{self._log_prefix} HTTP ✗ {method} {path_for_log} "
                f"failed after {elapsed_ms:.2f}ms (app time)"
            )
            raise
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            f"{self._log_prefix} HTTP → {method} {path_for_log} "
            f"status={response.status_code} "
            f"app_time={elapsed_ms:.2f}ms x-user-id={user_hint}"
        )
        return response
