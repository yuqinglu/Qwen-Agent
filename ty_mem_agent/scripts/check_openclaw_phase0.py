#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenClaw 集成 — 阶段 0 自检（ty-mem-agent 侧）

在仓库根目录 Qwen-Agent/ 下执行:
    python ty_mem_agent/scripts/check_openclaw_phase0.py

仅读取 ty_mem_agent/.env 与环境变量，不 import ty_mem_agent（避免未安装依赖时失败）。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


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

    print("=== ty-mem-agent · OpenClaw 阶段 0 自检 ===\n")
    print("详细计划: ty_mem_agent/doc/OPENCLAW_INTEGRATION_RUNBOOK.md\n")

    _en = _get("OPENCLAW_ENABLED", "true").lower()
    if _en in ("0", "false", "no", "off"):
        print("[INFO] OPENCLAW_ENABLED=false，跳过 OpenClaw 联调项检查（功能已关闭）\n")
        return 0

    host = _get("HOST", "0.0.0.0")
    try:
        port = int(_get("PORT", "8080"))
    except ValueError:
        port = 8080

    print(f"本服务监听（来自 .env）: http://{host}:{port}")
    cb_base = _get("OPENCLAW_CALLBACK_BASE_URL")
    if cb_base:
        cb = cb_base.rstrip("/")
        print(f"回调基础 URL: {cb}")
        print(f"  → 适配层将 POST: {cb}/agent/api/v1/chat/openclaw/callback")
    else:
        print("回调基础 URL: (未配置)")

    base = _get("OPENCLAW_API_BASE")
    print(f"\n适配层 API 根地址 OPENCLAW_API_BASE: {base or '(未配置 — 未启用适配层联调)'}")

    errors: list[str] = []
    warnings: list[str] = []

    if base:
        b = base.rstrip("/")
        if not b.endswith("/openclaw-adapter/v1"):
            warnings.append(
                "OPENCLAW_API_BASE 应以 /openclaw-adapter/v1 结尾（与 openclaw_adapter 路由一致），"
                f"当前: {base!r}"
            )
        if not _get("OPENCLAW_API_KEY"):
            errors.append("已配置 OPENCLAW_API_BASE 但缺少 OPENCLAW_API_KEY（应对齐适配层 ADAPTER_API_KEY）")
        if not _get("OPENCLAW_CALLBACK_SECRET"):
            errors.append(
                "已配置 OPENCLAW_API_BASE 但缺少 OPENCLAW_CALLBACK_SECRET（应对齐适配层 TY_MEM_CALLBACK_HMAC_SECRET）"
            )
        if not cb_base:
            errors.append(
                "已配置 OPENCLAW_API_BASE 但缺少 OPENCLAW_CALLBACK_BASE_URL（适配层无法回调本服务）"
            )
    else:
        warnings.append("未配置 OPENCLAW_API_BASE — 跳过与适配层相关的强校验（若暂不联调 OpenClaw 属正常）")

    print("\n--- 结果 ---")
    for w in warnings:
        print(f"[WARN] {w}")
    for e in errors:
        print(f"[ERROR] {e}")

    if not warnings and not errors:
        print("[OK] 未发现阶段 0 配置问题（若已启用适配层，请继续按 RUNBOOK 阶段 1 启动适配层）")
    elif not errors:
        print("\n[INFO] 仅有警告，可按 RUNBOOK 修正后继续。")
    else:
        print("\n[INFO] 存在错误项，请修正 ty_mem_agent/.env 后重跑本脚本。")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
