# -*- coding: utf-8 -*-
"""
异步任务管理器

使用 SQLite 持久化存储提交给 OpenClaw 的异步任务状态。
提供 CRUD 操作、按用户/会话查询、状态更新等接口。

表结构：async_tasks
  task_id          TEXT PRIMARY KEY   — 我们系统生成的幂等任务 ID（UUID）
  user_id          INTEGER            — 用户 ID（calendar_user_id）
  session_id       TEXT               — 关联的聊天会话 ID
  message_id       TEXT               — 触发任务的用户消息 ID
  task_type        TEXT               — periodic | research | one_time
  status           TEXT               — pending | running | done | failed | cancelled
  fallback_reason  TEXT               — inability_response | llm_periodic_intent | execution_error | timeout 等
  task_description TEXT               — 任务描述（自然语言）
  original_message TEXT               — 用户原始消息
  schedule         TEXT               — cron 表达式（仅 periodic 有效）
  openclaw_task_id TEXT               — OpenClaw 侧返回的任务 ID
  result_summary   TEXT               — 执行结果摘要（Markdown）
  next_run_at      TEXT               — 下次执行时间（ISO 格式，仅 periodic 有效）
  created_at       TEXT               — 创建时间（ISO 格式）
  updated_at       TEXT               — 最后更新时间（ISO 格式）
"""

import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from loguru import logger


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class AsyncTask:
    """一条异步任务记录"""
    task_id: str
    user_id: int
    session_id: str
    message_id: str
    task_type: str                    # periodic | research | one_time
    status: str                       # pending | running | done | failed | cancelled
    task_description: str
    original_message: str
    fallback_reason: Optional[str] = None
    schedule: Optional[str] = None
    openclaw_task_id: Optional[str] = None
    result_summary: Optional[str] = None
    next_run_at: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = datetime.now().isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "AsyncTask":
        d = dict(row)
        return cls(
            task_id=d["task_id"],
            user_id=d["user_id"],
            session_id=d["session_id"],
            message_id=d["message_id"],
            task_type=d["task_type"],
            status=d["status"],
            task_description=d["task_description"],
            original_message=d["original_message"],
            fallback_reason=d.get("fallback_reason"),
            schedule=d.get("schedule"),
            openclaw_task_id=d.get("openclaw_task_id"),
            result_summary=d.get("result_summary"),
            next_run_at=d.get("next_run_at"),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )


# ---------------------------------------------------------------------------
# 管理器
# ---------------------------------------------------------------------------

class AsyncTaskManager:
    """异步任务 SQLite 管理器（单例）"""

    _instance: Optional["AsyncTaskManager"] = None

    def __new__(cls) -> "AsyncTaskManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = True
        self._db_path = self._resolve_db_path()
        self._init_db()
        logger.info(f"[AsyncTaskManager] 初始化完成，数据库路径: {self._db_path}")

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def _resolve_db_path(self) -> Path:
        try:
            from ty_mem_agent.config.settings import settings
            data_dir = Path(settings.DATA_DIR)
        except Exception:
            data_dir = Path(__file__).parent.parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "async_tasks.db"

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS async_tasks (
                    task_id          TEXT PRIMARY KEY,
                    user_id          INTEGER NOT NULL,
                    session_id       TEXT NOT NULL,
                    message_id       TEXT NOT NULL,
                    task_type        TEXT NOT NULL DEFAULT 'one_time',
                    status           TEXT NOT NULL DEFAULT 'pending',
                    fallback_reason  TEXT,
                    task_description TEXT NOT NULL,
                    original_message TEXT NOT NULL,
                    schedule         TEXT,
                    openclaw_task_id TEXT,
                    result_summary   TEXT,
                    next_run_at      TEXT,
                    created_at       TEXT NOT NULL,
                    updated_at       TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON async_tasks(user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_session_id ON async_tasks(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON async_tasks(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_openclaw_id ON async_tasks(openclaw_task_id)")

    # ------------------------------------------------------------------
    # 创建任务
    # ------------------------------------------------------------------

    def create_task(
        self,
        user_id: int,
        session_id: str,
        message_id: str,
        task_description: str,
        original_message: str,
        task_type: str = "one_time",
        fallback_reason: Optional[str] = None,
        schedule: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> AsyncTask:
        """创建并持久化一条异步任务记录，返回已保存的任务对象。"""
        task = AsyncTask(
            task_id=task_id or str(uuid.uuid4()),
            user_id=user_id,
            session_id=session_id,
            message_id=message_id,
            task_type=task_type,
            status="pending",
            task_description=task_description,
            original_message=original_message,
            fallback_reason=fallback_reason,
            schedule=schedule,
        )
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO async_tasks (
                    task_id, user_id, session_id, message_id, task_type, status,
                    fallback_reason, task_description, original_message,
                    schedule, openclaw_task_id, result_summary, next_run_at,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    task.task_id, task.user_id, task.session_id, task.message_id,
                    task.task_type, task.status, task.fallback_reason,
                    task.task_description, task.original_message,
                    task.schedule, task.openclaw_task_id, task.result_summary,
                    task.next_run_at, task.created_at, task.updated_at,
                ),
            )
        logger.debug(f"[AsyncTaskManager] 任务已创建: task_id={task.task_id}, type={task_type}")
        return task

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_task(self, task_id: str) -> Optional[AsyncTask]:
        """按 task_id 查询单条任务。"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM async_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        return AsyncTask.from_row(row) if row else None

    def get_task_by_openclaw_id(self, openclaw_task_id: str) -> Optional[AsyncTask]:
        """按 openclaw_task_id 查询任务（用于处理回调）。"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM async_tasks WHERE openclaw_task_id = ?",
                (openclaw_task_id,),
            ).fetchone()
        return AsyncTask.from_row(row) if row else None

    def list_tasks_by_user(
        self,
        user_id: int,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[AsyncTask]:
        """按用户查询任务列表，支持状态过滤，按创建时间倒序。"""
        with self._get_conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM async_tasks WHERE user_id=? AND status=? "
                    "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (user_id, status, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM async_tasks WHERE user_id=? "
                    "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (user_id, limit, offset),
                ).fetchall()
        return [AsyncTask.from_row(r) for r in rows]

    def list_tasks_by_session(self, session_id: str) -> List[AsyncTask]:
        """按会话查询任务列表。"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM async_tasks WHERE session_id=? ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
        return [AsyncTask.from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # 更新
    # ------------------------------------------------------------------

    def update_openclaw_id(self, task_id: str, openclaw_task_id: str) -> bool:
        """任务提交 OpenClaw 成功后，记录 OpenClaw 侧任务 ID。"""
        return self._update_fields(
            task_id,
            {"openclaw_task_id": openclaw_task_id, "status": "running"},
        )

    def update_result(
        self,
        task_id: str,
        result_summary: str,
        status: str = "done",
        next_run_at: Optional[str] = None,
    ) -> bool:
        """OpenClaw 回调后更新执行结果。"""
        fields: Dict[str, Any] = {"result_summary": result_summary, "status": status}
        if next_run_at:
            fields["next_run_at"] = next_run_at
        return self._update_fields(task_id, fields)

    def update_status(self, task_id: str, status: str) -> bool:
        """更新任务状态。"""
        return self._update_fields(task_id, {"status": status})

    def _update_fields(self, task_id: str, fields: Dict[str, Any]) -> bool:
        """通用字段更新。"""
        fields["updated_at"] = datetime.now().isoformat()
        set_clause = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [task_id]
        try:
            with self._get_conn() as conn:
                conn.execute(
                    f"UPDATE async_tasks SET {set_clause} WHERE task_id=?",
                    values,
                )
            return True
        except Exception as e:
            logger.error(f"[AsyncTaskManager] 更新任务失败: task_id={task_id}, err={e}")
            return False

    # ------------------------------------------------------------------
    # 删除 / 取消
    # ------------------------------------------------------------------

    def cancel_task(self, task_id: str) -> bool:
        """标记任务为 cancelled。"""
        return self.update_status(task_id, "cancelled")

    def delete_task(self, task_id: str) -> bool:
        """物理删除任务记录。"""
        try:
            with self._get_conn() as conn:
                conn.execute("DELETE FROM async_tasks WHERE task_id=?", (task_id,))
            return True
        except Exception as e:
            logger.error(f"[AsyncTaskManager] 删除任务失败: {e}")
            return False


# ---------------------------------------------------------------------------
# 单例访问
# ---------------------------------------------------------------------------

_manager: Optional[AsyncTaskManager] = None


def get_async_task_manager() -> AsyncTaskManager:
    """获取 AsyncTaskManager 单例。"""
    global _manager
    if _manager is None:
        _manager = AsyncTaskManager()
    return _manager
