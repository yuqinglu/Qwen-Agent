# -*- coding: utf-8 -*-
"""Best-effort parse of OpenClaw Gateway webhook JSON (shape varies by version)."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


def extract_job_id(data: Dict[str, Any]) -> Optional[str]:
    for key in ("jobId", "job_id", "cronJobId", "cron_job_id", "id"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, int):
            return str(v)
    for nest_key in ("job", "cron", "cronJob", "payload", "event"):
        sub = data.get(nest_key)
        if isinstance(sub, dict):
            inner = extract_job_id(sub)
            if inner:
                return inner
    return None


def extract_result_text(data: Dict[str, Any]) -> str:
    for key in ("summary", "text", "result", "content", "message", "output", "body"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for nest_key in ("finished", "event", "data", "payload", "result"):
        sub = data.get(nest_key)
        if isinstance(sub, dict):
            t = extract_result_text(sub)
            if t:
                return t
    try:
        return json.dumps(data, ensure_ascii=False)[:8000]
    except Exception:
        return str(data)[:8000]


def extract_next_run_at(data: Dict[str, Any]) -> Optional[str]:
    for key in ("nextRunAt", "next_run_at", "nextRun", "scheduledAt"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    sub = data.get("schedule") or data.get("job")
    if isinstance(sub, dict):
        return extract_next_run_at(sub)
    return None


def extract_status_ok(data: Dict[str, Any]) -> bool:
    s = data.get("status") or data.get("state")
    if isinstance(s, str):
        if s.lower() in ("failed", "error", "cancelled"):
            return False
        if s.lower() in ("ok", "done", "success", "completed"):
            return True
    err = data.get("error") or data.get("errorMessage")
    if err:
        return False
    return True
