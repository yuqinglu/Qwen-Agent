# -*- coding: utf-8 -*-
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class TaskCreateRequest(BaseModel):
    client_task_id: str
    user_id: str
    task_description: str
    original_message: str
    callback_url: str
    task_type: str = Field(..., description="periodic | research | one_time")
    schedule: Optional[str] = None
    schedule_timezone: Optional[str] = "Asia/Shanghai"
    fallback_reason: str = "unknown"
    context: Optional[Dict[str, Any]] = None


class TaskCreateResponse(BaseModel):
    openclaw_task_id: str
    client_task_id: str
    status: str = "accepted"


class TaskStatusResponse(BaseModel):
    openclaw_task_id: str
    client_task_id: str
    status: str
    task_type: str
    created_at: Optional[str] = None
    last_executed_at: Optional[str] = None
    next_run_at: Optional[str] = None
    result_summary: Optional[str] = None
