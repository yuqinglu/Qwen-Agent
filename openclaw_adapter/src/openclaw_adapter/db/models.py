# -*- coding: utf-8 -*-
"""SQLAlchemy ORM models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, String, Text, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AdapterTask(Base):
    __tablename__ = "adapter_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_task_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # ID returned to ty-mem-agent as openclaw_task_id (usually gateway jobId)
    openclaw_task_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    gateway_job_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)

    user_id: Mapped[str] = mapped_column(String(64), index=True)
    callback_url: Mapped[str] = mapped_column(Text)
    task_type: Mapped[str] = mapped_column(String(32))
    schedule: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    schedule_timezone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    task_description: Mapped[str] = mapped_column(Text)
    original_message: Mapped[str] = mapped_column(Text)
    fallback_reason: Mapped[str] = mapped_column(String(64), default="unknown")
    context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="accepted", index=True)
    last_result_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    next_run_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
