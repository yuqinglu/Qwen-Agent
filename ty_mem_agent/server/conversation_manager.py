#!/usr/bin/env python3
"""
会话历史管理模块
负责管理用户的聊天会话历史、消息存储和会话切换。

持久化使用 SQLite（conversations.sqlite）：会话元数据与消息分表，列表查询走索引，与全量消息加载解耦。
内存 ``self.conversations`` 为按需填充的缓存。
"""

import uuid
from pathlib import Path
from typing import Dict, List, Optional

from dataclasses import dataclass, asdict
from datetime import datetime
from loguru import logger

from .conversation_sqlite_store import ConversationSqliteStore


@dataclass
class ConversationMessage:
    """会话消息"""

    message_id: str
    role: str  # 'user' 或 'assistant'
    content: str
    timestamp: str
    metadata: Optional[Dict] = None


@dataclass
class Conversation:
    """会话对象"""

    conversation_id: str
    user_id: str
    title: str
    created_at: str
    updated_at: str
    messages: List[ConversationMessage]

    def to_dict(self):
        """转换为字典"""
        return {
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": len(self.messages),
            "messages": [asdict(msg) for msg in self.messages],
        }

    def to_summary(self):
        """转换为摘要（不包含消息内容）"""
        return {
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": len(self.messages),
            "last_message_preview": self.messages[-1].content[:50] if self.messages else "",
        }


class ConversationManager:
    """会话管理器（SQLite 持久化 + 内存缓存）"""

    def __init__(self, data_dir: Optional[Path] = None):
        if data_dir is None:
            data_dir = Path(__file__).parent.parent / "data" / "conversations"

        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._store = ConversationSqliteStore(self.data_dir)
        self._store.migrate_from_json_files()

        # 按需缓存完整会话（含消息）
        self.conversations: Dict[str, Conversation] = {}

        # user_id -> conversation_id，避免列表外路径的全表扫描
        self._user_conversation_ids: Dict[str, set] = {}
        self._rebuild_user_index()

        logger.info(f"📚 会话管理器初始化完成（SQLite），数据目录: {self.data_dir}")

    def _rebuild_user_index(self) -> None:
        """从 DB 重建 user_id 索引（启动或修复用）。"""
        self._user_conversation_ids.clear()
        for row in self._store.fetch_all_conversation_ids_by_user():
            uid, cid = row["user_id"], row["conversation_id"]
            self._user_conversation_ids.setdefault(uid, set()).add(cid)

    def _index_add(self, user_id: str, conversation_id: str) -> None:
        self._user_conversation_ids.setdefault(user_id, set()).add(conversation_id)

    def _index_remove(self, user_id: str, conversation_id: str) -> None:
        s = self._user_conversation_ids.get(user_id)
        if not s:
            return
        s.discard(conversation_id)
        if not s:
            del self._user_conversation_ids[user_id]

    def _index_rename(self, user_id: str, old_id: str, new_id: str) -> None:
        self._index_remove(user_id, old_id)
        self._index_add(user_id, new_id)

    def _conversation_from_db_rows(
        self, meta: Dict, msg_dicts: List[Dict]
    ) -> Conversation:
        messages = []
        for m in msg_dicts:
            messages.append(
                ConversationMessage(
                    message_id=m["message_id"],
                    role=m["role"],
                    content=m["content"],
                    timestamp=m["timestamp"],
                    metadata=m.get("metadata"),
                )
            )
        return Conversation(
            conversation_id=meta["conversation_id"],
            user_id=meta["user_id"],
            title=meta["title"],
            created_at=meta["created_at"],
            updated_at=meta["updated_at"],
            messages=messages,
        )

    def _load_into_cache(self, conversation_id: str) -> Optional[Conversation]:
        if conversation_id in self.conversations:
            return self.conversations[conversation_id]
        packed = self._store.fetch_conversation_with_messages(conversation_id)
        if not packed:
            return None
        meta, msg_dicts = packed
        conv = self._conversation_from_db_rows(meta, msg_dicts)
        self.conversations[conversation_id] = conv
        return conv

    def rename_conversation_id(self, old_id: str, new_id: str) -> None:
        """将会话 ID 从 old_id 改为 new_id（通用聊天 gc_ 前缀场景）。"""
        if old_id == new_id:
            return
        conv = self.conversations.pop(old_id, None)
        uid = conv.user_id if conv else None
        if uid is None:
            packed = self._store.fetch_conversation_with_messages(old_id)
            if packed:
                uid = packed[0]["user_id"]
        self._store.rename_conversation_id(old_id, new_id)
        if conv:
            conv.conversation_id = new_id
            self.conversations[new_id] = conv
        if uid is not None:
            self._index_rename(uid, old_id, new_id)

    def create_conversation(self, user_id: str, title: str = "新对话") -> Conversation:
        conversation_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        user_id = str(user_id)
        conversation = Conversation(
            conversation_id=conversation_id,
            user_id=user_id,
            title=title,
            created_at=now,
            updated_at=now,
            messages=[],
        )

        self._store.insert_conversation(
            conversation_id, user_id, title, now, now
        )
        self.conversations[conversation_id] = conversation
        self._index_add(user_id, conversation_id)

        logger.info(f"✅ 创建新会话: {conversation_id} - {title}")
        return conversation

    def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        """获取指定会话（按需从 SQLite 加载到缓存）。"""
        return self._load_into_cache(conversation_id)

    def get_user_conversations(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> List[Dict]:
        """
        获取用户会话摘要列表，按更新时间倒序。
        使用 SQLite 索引查询，不加载消息正文。
        """
        return self._store.fetch_summaries(str(user_id), limit, offset)

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict] = None,
    ) -> Optional[ConversationMessage]:
        conversation = self._load_into_cache(conversation_id)
        if not conversation:
            logger.warning(f"会话不存在: {conversation_id}")
            return None

        message_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        seq = len(conversation.messages)

        message = ConversationMessage(
            message_id=message_id,
            role=role,
            content=content,
            timestamp=timestamp,
            metadata=metadata,
        )

        self._store.append_message(
            conversation_id,
            seq,
            message_id,
            role,
            content,
            timestamp,
            metadata,
        )

        conversation.messages.append(message)
        conversation.updated_at = timestamp

        logger.debug(
            f"📝 添加消息到会话 {conversation_id}: {role} - {content[:50]}..."
        )
        return message

    def update_conversation_title(self, conversation_id: str, title: str) -> bool:
        conversation = self._load_into_cache(conversation_id)
        if not conversation:
            logger.warning(f"会话不存在: {conversation_id}")
            return False

        now = datetime.now().isoformat()
        conversation.title = title
        conversation.updated_at = now
        self._store.update_conversation_meta(conversation_id, title=title, updated_at=now)

        logger.info(f"✅ 更新会话标题: {conversation_id} -> {title}")
        return True

    def delete_conversation(self, conversation_id: str) -> bool:
        conv = self.conversations.pop(conversation_id, None)
        uid = conv.user_id if conv else None
        if uid is None:
            packed = self._store.fetch_conversation_with_messages(conversation_id)
            if packed:
                uid = packed[0]["user_id"]

        ok = self._store.delete_conversation(conversation_id)
        if not ok:
            logger.warning(f"会话不存在: {conversation_id}")
            return False

        if uid is not None:
            self._index_remove(uid, conversation_id)

        logger.info(f"🗑️  删除会话: {conversation_id}")
        return True

    def get_conversation_messages(self, conversation_id: str) -> List[Dict]:
        conv = self._load_into_cache(conversation_id)
        if not conv:
            return []
        return [asdict(msg) for msg in conv.messages]


# 全局单例
_conversation_manager: Optional[ConversationManager] = None


def get_conversation_manager() -> ConversationManager:
    """获取会话管理器单例"""
    global _conversation_manager
    if _conversation_manager is None:
        _conversation_manager = ConversationManager()
    return _conversation_manager
