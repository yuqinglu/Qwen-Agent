#!/usr/bin/env python3
"""
SQLite persistence for ConversationManager: session metadata + messages on separate rows.
List queries use indexed columns only (decoupled from loading full message bodies).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


class ConversationSqliteStore:
    """Thread-safe SQLite store under ``data_dir / conversations.sqlite``."""

    def __init__(self, data_dir: Path):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_dir / "conversations.sqlite"
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS conversations (
                        conversation_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        message_count INTEGER NOT NULL DEFAULT 0,
                        last_message_preview TEXT NOT NULL DEFAULT ''
                    );
                    CREATE INDEX IF NOT EXISTS idx_conversations_user_updated
                    ON conversations (user_id, updated_at DESC);

                    CREATE TABLE IF NOT EXISTS messages (
                        conversation_id TEXT NOT NULL,
                        seq INTEGER NOT NULL,
                        message_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        metadata_json TEXT,
                        PRIMARY KEY (conversation_id, seq),
                        UNIQUE (message_id),
                        FOREIGN KEY (conversation_id)
                            REFERENCES conversations (conversation_id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS idx_messages_conversation_seq
                    ON messages (conversation_id, seq);
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def migrate_from_json_files(self) -> int:
        """Import any ``*.json`` sessions not yet present in the DB. Returns count imported."""
        imported = 0
        for conv_file in sorted(self._data_dir.glob("*.json")):
            try:
                with open(conv_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                cid = data.get("conversation_id")
                if not cid:
                    continue
                with self._lock:
                    conn = self._connect()
                    try:
                        row = conn.execute(
                            "SELECT 1 FROM conversations WHERE conversation_id = ?",
                            (cid,),
                        ).fetchone()
                        if row:
                            continue
                        msgs = data.get("messages") or []
                        preview = ""
                        if msgs:
                            last = msgs[-1]
                            preview = (last.get("content") or "")[:50]
                        conn.execute(
                            """
                            INSERT INTO conversations (
                                conversation_id, user_id, title, created_at, updated_at,
                                message_count, last_message_preview
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                cid,
                                str(data["user_id"]),
                                data["title"],
                                data["created_at"],
                                data["updated_at"],
                                len(msgs),
                                preview,
                            ),
                        )
                        for seq, msg in enumerate(msgs):
                            meta = msg.get("metadata")
                            conn.execute(
                                """
                                INSERT INTO messages (
                                    conversation_id, seq, message_id, role, content,
                                    timestamp, metadata_json
                                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    cid,
                                    seq,
                                    msg["message_id"],
                                    msg["role"],
                                    msg["content"],
                                    msg["timestamp"],
                                    json.dumps(meta, ensure_ascii=False) if meta is not None else None,
                                ),
                            )
                        conn.commit()
                        imported += 1
                    finally:
                        conn.close()
            except Exception as e:
                logger.error(f"SQLite 迁移 JSON 失败 {conv_file}: {e}")
        if imported:
            logger.info(f"✅ SQLite 已从 JSON 导入 {imported} 个会话")
        return imported

    def insert_conversation(
        self,
        conversation_id: str,
        user_id: str,
        title: str,
        created_at: str,
        updated_at: str,
    ) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO conversations (
                        conversation_id, user_id, title, created_at, updated_at,
                        message_count, last_message_preview
                    ) VALUES (?, ?, ?, ?, ?, 0, '')
                    """,
                    (conversation_id, user_id, title, created_at, updated_at),
                )
                conn.commit()
            finally:
                conn.close()

    def rename_conversation_id(self, old_id: str, new_id: str) -> None:
        if old_id == new_id:
            return
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO conversations (
                        conversation_id, user_id, title, created_at, updated_at,
                        message_count, last_message_preview
                    )
                    SELECT ?, user_id, title, created_at, updated_at,
                           message_count, last_message_preview
                    FROM conversations WHERE conversation_id = ?
                    """,
                    (new_id, old_id),
                )
                conn.execute(
                    "UPDATE messages SET conversation_id = ? WHERE conversation_id = ?",
                    (new_id, old_id),
                )
                conn.execute(
                    "DELETE FROM conversations WHERE conversation_id = ?", (old_id,)
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "DELETE FROM conversations WHERE conversation_id = ?",
                    (conversation_id,),
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def update_conversation_meta(
        self,
        conversation_id: str,
        *,
        title: Optional[str] = None,
        updated_at: Optional[str] = None,
    ) -> bool:
        sets: List[str] = []
        args: List[Any] = []
        if title is not None:
            sets.append("title = ?")
            args.append(title)
        if updated_at is not None:
            sets.append("updated_at = ?")
            args.append(updated_at)
        if not sets:
            return False
        args.append(conversation_id)
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    f"UPDATE conversations SET {', '.join(sets)} WHERE conversation_id = ?",
                    args,
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def append_message(
        self,
        conversation_id: str,
        seq: int,
        message_id: str,
        role: str,
        content: str,
        timestamp: str,
        metadata: Optional[Dict],
    ) -> None:
        preview = (content or "")[:50]
        meta_json = json.dumps(metadata, ensure_ascii=False) if metadata is not None else None
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO messages (
                        conversation_id, seq, message_id, role, content,
                        timestamp, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        conversation_id,
                        seq,
                        message_id,
                        role,
                        content,
                        timestamp,
                        meta_json,
                    ),
                )
                conn.execute(
                    """
                    UPDATE conversations SET
                        updated_at = ?,
                        message_count = message_count + 1,
                        last_message_preview = ?
                    WHERE conversation_id = ?
                    """,
                    (timestamp, preview, conversation_id),
                )
                conn.commit()
            finally:
                conn.close()

    def fetch_summaries(
        self, user_id: str, limit: int, offset: int
    ) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT conversation_id, user_id, title, created_at, updated_at,
                           message_count, last_message_preview
                    FROM conversations
                    WHERE user_id = ?
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (user_id, limit, offset),
                ).fetchall()
                return [
                    {
                        "conversation_id": r["conversation_id"],
                        "user_id": r["user_id"],
                        "title": r["title"],
                        "created_at": r["created_at"],
                        "updated_at": r["updated_at"],
                        "message_count": r["message_count"],
                        "last_message_preview": r["last_message_preview"] or "",
                    }
                    for r in rows
                ]
            finally:
                conn.close()

    def fetch_conversation_with_messages(
        self, conversation_id: str
    ) -> Optional[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
        with self._lock:
            conn = self._connect()
            try:
                crow = conn.execute(
                    """
                    SELECT conversation_id, user_id, title, created_at, updated_at,
                           message_count, last_message_preview
                    FROM conversations WHERE conversation_id = ?
                    """,
                    (conversation_id,),
                ).fetchone()
                if not crow:
                    return None
                meta = dict(crow)
                mrows = conn.execute(
                    """
                    SELECT message_id, role, content, timestamp, metadata_json
                    FROM messages WHERE conversation_id = ?
                    ORDER BY seq ASC
                    """,
                    (conversation_id,),
                ).fetchall()
                messages = []
                for r in mrows:
                    md = None
                    if r["metadata_json"]:
                        try:
                            md = json.loads(r["metadata_json"])
                        except json.JSONDecodeError:
                            md = None
                    messages.append(
                        {
                            "message_id": r["message_id"],
                            "role": r["role"],
                            "content": r["content"],
                            "timestamp": r["timestamp"],
                            "metadata": md,
                        }
                    )
                return meta, messages
            finally:
                conn.close()

    def fetch_all_conversation_ids_by_user(self):
        """返回所有会话的 (conversation_id, user_id)，用于重建内存索引。"""
        with self._lock:
            conn = self._connect()
            try:
                return conn.execute(
                    "SELECT conversation_id, user_id FROM conversations"
                ).fetchall()
            finally:
                conn.close()

    def conversation_exists(self, conversation_id: str) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                r = conn.execute(
                    "SELECT 1 FROM conversations WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()
                return r is not None
            finally:
                conn.close()

    def replace_all_messages(
        self,
        conversation_id: str,
        messages: List[Dict[str, Any]],
    ) -> None:
        """Rewrite messages for a conversation (used when syncing from in-memory model)."""
        preview = ""
        if messages:
            preview = (messages[-1].get("content") or "")[:50]
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
                )
                for seq, msg in enumerate(messages):
                    meta = msg.get("metadata")
                    conn.execute(
                        """
                        INSERT INTO messages (
                            conversation_id, seq, message_id, role, content,
                            timestamp, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            conversation_id,
                            seq,
                            msg["message_id"],
                            msg["role"],
                            msg["content"],
                            msg["timestamp"],
                            json.dumps(meta, ensure_ascii=False) if meta is not None else None,
                        ),
                    )
                conn.execute(
                    """
                    UPDATE conversations SET
                        message_count = ?,
                        last_message_preview = ?
                    WHERE conversation_id = ?
                    """,
                    (len(messages), preview, conversation_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
