#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenClaw 适配层 — 阶段 0 自检

在 openclaw_adapter/ 目录下执行:
    python scripts/check_phase0.py

不依赖已安装包：仅解析本目录 .env 与环境变量。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ENV_PATH = _ROOT / ".env"


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1].replace('\\"', '"')
        elif val.startswith("'") and val.endswith("'"):
            val = val[1:-1]
        if key not in os.environ:
            os.environ[key] = val


def _get(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def main() -> int:
    _load_dotenv(_ENV_PATH)

    print("=== openclaw_adapter · 阶段 0 自检 ===\n")
    print("联调计划: ty_mem_agent/doc/OPENCLAW_INTEGRATION_RUNBOOK.md\n")

    host = _get("ADAPTER_HOST", "0.0.0.0")
    try:
        port = int(_get("ADAPTER_PORT", "8090"))
    except ValueError:
        port = 8090

    pub = _get("ADAPTER_PUBLIC_BASE_URL", "http://127.0.0.1:8090")
    mode = _get("ADAPTER_GATEWAY_MODE", "stub")

    print(f"监听: {host}:{port}")
    print(f"ADAPTER_PUBLIC_BASE_URL: {pub}")
    prefix = "/openclaw-adapter"
    print(f"  → Webhook 入站: {pub.rstrip('/')}{prefix}/internal/openclaw/webhook")
    print(f"  → ty-mem 应配置 OPENCLAW_API_BASE: {pub.rstrip('/')}{prefix}/v1")
    print(f"ADAPTER_GATEWAY_MODE: {mode}")

    errors: list[str] = []
    warnings: list[str] = []

    if not _get("ADAPTER_API_KEY"):
        warnings.append(
            "ADAPTER_API_KEY 为空 — ty-mem 调用 /openclaw-adapter/v1/tasks 将无法鉴权（生产必须设置）"
        )

    if not _get("TY_MEM_CALLBACK_HMAC_SECRET"):
        warnings.append(
            "TY_MEM_CALLBACK_HMAC_SECRET 为空 — 转发 ty-mem 回调将无法带有效 HMAC（生产必须设置）"
        )

    if mode.lower() == "http":
        if not _get("ADAPTER_GATEWAY_HTTP_URL"):
            errors.append("ADAPTER_GATEWAY_MODE=http 但未设置 ADAPTER_GATEWAY_HTTP_URL")
    elif mode.lower() == "stub":
        warnings.append(
            "当前为 stub 模式；联调 ty-mem 请配合 ADAPTER_DEV_ENDPOINTS 与 simulate-callback（见 RUNBOOK 阶段1）"
        )

    if "127.0.0.1" in pub or "localhost" in pub.lower():
        warnings.append(
            "ADAPTER_PUBLIC_BASE_URL 为回环地址 — Gateway 若在其它机器则无法 POST webhook，请换内网 IP/域名"
        )

    print("\n--- 结果 ---")
    for w in warnings:
        print(f"[WARN] {w}")
    for e in errors:
        print(f"[ERROR] {e}")

    if errors:
        return 1
    print("[OK] 阶段 0 适配层检查完成（请与 ty-mem 侧脚本及 RUNBOOK 密钥表交叉核对）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
