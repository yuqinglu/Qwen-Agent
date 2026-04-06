# -*- coding: utf-8 -*-
"""Async engine and session."""

from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from openclaw_adapter.config import get_settings
from openclaw_adapter.db.models import Base


_engine = None
_session_factory = None


def _ensure_sqlite_dir(url: str) -> None:
    if url.startswith("sqlite+aiosqlite:///./") or url.startswith("sqlite+aiosqlite://"):
        # ./data/adapter.db
        raw = url.replace("sqlite+aiosqlite:///", "").replace("sqlite+aiosqlite://", "")
        if "/" in raw or raw.startswith("."):
            p = Path(raw.split("?")[0])
            if not p.is_absolute():
                p = Path.cwd() / p
            p.parent.mkdir(parents=True, exist_ok=True)


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _ensure_sqlite_dir(settings.database_url)
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
        )
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        yield session


async def init_db() -> None:
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
