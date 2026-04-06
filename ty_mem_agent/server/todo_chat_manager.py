#!/usr/bin/env python3
"""
待办聊天会话管理器
管理待办页面的AI聊天会话和消息
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, asdict, field
from loguru import logger


@dataclass
class ChatMessage:
    """聊天消息"""
    message_id: str
    role: str  # "user" or "assistant"
    content: str
    timestamp: str
    # AI回复特有字段
    todo_content: Optional[str] = None
    suggested_todos: List[Dict] = field(default_factory=list)
    rich_cards: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "message_id": self.message_id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "todo_content": self.todo_content,
            "suggested_todos": self.suggested_todos,
            "rich_cards": self.rich_cards
        }


@dataclass
class TodoChatSession:
    """待办聊天会话"""
    session_id: str
    event_id: int
    user_id: int  # calendar_user_id
    title: str
    created_at: str
    updated_at: str
    messages: List[ChatMessage] = field(default_factory=list)
    # 会话上下文
    todo_content: Optional[str] = None  # 关联的待办正文
    rich_cards: List[Dict] = field(default_factory=list)  # 关联的富媒体卡片
    
    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "event_id": self.event_id,
            "user_id": self.user_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [msg.to_dict() for msg in self.messages],
            "todo_content": self.todo_content,
            "rich_cards": self.rich_cards
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "TodoChatSession":
        messages = [
            ChatMessage(
                message_id=msg["message_id"],
                role=msg["role"],
                content=msg["content"],
                timestamp=msg["timestamp"],
                todo_content=msg.get("todo_content"),
                suggested_todos=msg.get("suggested_todos", []),
                rich_cards=msg.get("rich_cards", [])
            )
            for msg in data.get("messages", [])
        ]
        return cls(
            session_id=data["session_id"],
            event_id=data["event_id"],
            user_id=data["user_id"],
            title=data["title"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            messages=messages,
            todo_content=data.get("todo_content"),
            rich_cards=data.get("rich_cards", [])
        )


class TodoChatManager:
    """待办聊天会话管理器"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TodoChatManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # 数据存储路径
        self.data_dir = Path(__file__).parent.parent / "data" / "todo_chat_sessions"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 内存缓存: {session_id: TodoChatSession}
        self.sessions: Dict[str, TodoChatSession] = {}
        # (event_id, user_id) -> session_id 集合，避免列表接口全表扫描
        self._event_user_session_ids: Dict[Tuple[int, int], Set[str]] = {}
        
        # 加载已有会话
        self._load_sessions()
        
        self._initialized = True
        logger.info(f"✅ 待办聊天管理器初始化完成，数据目录: {self.data_dir}")
    
    def _index_key(self, event_id: int, user_id: int) -> Tuple[int, int]:
        return (event_id, user_id)
    
    def _index_add_session(self, session: TodoChatSession) -> None:
        key = self._index_key(session.event_id, session.user_id)
        self._event_user_session_ids.setdefault(key, set()).add(session.session_id)
    
    def _index_remove_session(self, session: TodoChatSession) -> None:
        key = self._index_key(session.event_id, session.user_id)
        s = self._event_user_session_ids.get(key)
        if s:
            s.discard(session.session_id)
            if not s:
                del self._event_user_session_ids[key]
    
    def _load_sessions(self):
        """从文件加载会话"""
        try:
            for file_path in self.data_dir.glob("*.json"):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        session = TodoChatSession.from_dict(data)
                        self.sessions[session.session_id] = session
                        self._index_add_session(session)
                except Exception as e:
                    logger.warning(f"⚠️ 加载会话文件失败 {file_path}: {e}")
            
            logger.info(f"📚 已加载 {len(self.sessions)} 个待办聊天会话")
        except Exception as e:
            logger.error(f"❌ 加载会话失败: {e}")
    
    def _save_session(self, session: TodoChatSession):
        """保存会话到文件"""
        try:
            file_path = self.data_dir / f"{session.session_id}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"❌ 保存会话失败: {e}")
    
    def create_session(
        self,
        event_id: int,
        user_id: int,
        title: str = "新对话",
        todo_content: Optional[str] = None,
        rich_cards: Optional[List[Dict]] = None
    ) -> TodoChatSession:
        """创建新的聊天会话"""
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        now = datetime.now().isoformat()
        
        session = TodoChatSession(
            session_id=session_id,
            event_id=event_id,
            user_id=user_id,
            title=title,
            created_at=now,
            updated_at=now,
            messages=[],
            todo_content=todo_content,
            rich_cards=rich_cards or []
        )
        
        self.sessions[session_id] = session
        self._index_add_session(session)
        self._save_session(session)
        
        logger.info(f"✅ 创建待办聊天会话: {session_id}, event_id={event_id}, user_id={user_id}")
        return session
    
    def get_session(self, session_id: str) -> Optional[TodoChatSession]:
        """获取会话"""
        return self.sessions.get(session_id)
    
    def get_sessions_by_event(self, event_id: int, user_id: int) -> List[TodoChatSession]:
        """获取指定待办的所有会话"""
        key = self._index_key(event_id, user_id)
        ids = self._event_user_session_ids.get(key, set())
        sessions = [
            self.sessions[sid] for sid in ids if sid in self.sessions
        ]
        sessions.sort(key=lambda x: x.updated_at, reverse=True)
        return sessions
    
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        todo_content: Optional[str] = None,
        suggested_todos: Optional[List[Dict]] = None,
        rich_cards: Optional[List[Dict]] = None
    ) -> Optional[ChatMessage]:
        """添加消息到会话"""
        session = self.sessions.get(session_id)
        if not session:
            logger.warning(f"⚠️ 会话不存在: {session_id}")
            return None
        
        message = ChatMessage(
            message_id=f"msg_{uuid.uuid4().hex[:12]}",
            role=role,
            content=content,
            timestamp=datetime.now().isoformat(),
            todo_content=todo_content,
            suggested_todos=suggested_todos or [],
            rich_cards=rich_cards or []
        )
        
        session.messages.append(message)
        session.updated_at = datetime.now().isoformat()
        self._save_session(session)
        
        logger.debug(f"📝 添加消息到会话 {session_id}: {role}, {content[:50]}...")
        return message
    
    def update_session_title(self, session_id: str, title: str) -> bool:
        """更新会话标题"""
        session = self.sessions.get(session_id)
        if not session:
            return False
        
        session.title = title
        session.updated_at = datetime.now().isoformat()
        self._save_session(session)
        
        logger.info(f"✅ 更新会话标题: {session_id} -> {title}")
        return True
    
    def update_session_context(
        self,
        session_id: str,
        todo_content: Optional[str] = None,
        rich_cards: Optional[List[Dict]] = None
    ) -> bool:
        """更新会话上下文（待办内容和富媒体卡片）"""
        session = self.sessions.get(session_id)
        if not session:
            return False
        
        if todo_content is not None:
            session.todo_content = todo_content
        
        if rich_cards is not None:
            session.rich_cards = rich_cards
        
        session.updated_at = datetime.now().isoformat()
        self._save_session(session)
        
        logger.info(f"✅ 更新会话上下文: {session_id}")
        return True
    
    def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        if session_id not in self.sessions:
            return False
        
        self._index_remove_session(self.sessions[session_id])
        del self.sessions[session_id]
        
        # 删除文件
        file_path = self.data_dir / f"{session_id}.json"
        if file_path.exists():
            file_path.unlink()
        
        logger.info(f"✅ 删除待办聊天会话: {session_id}")
        return True
    
    def get_session_messages(
        self,
        session_id: str,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """获取会话消息（分页）"""
        session = self.sessions.get(session_id)
        if not session:
            return {"messages": [], "total": 0, "page": page, "page_size": page_size}
        
        total = len(session.messages)
        start = (page - 1) * page_size
        end = start + page_size
        
        # 按时间正序返回
        messages = session.messages[start:end]
        
        return {
            "messages": [msg.to_dict() for msg in messages],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": end < total
        }


# 全局实例
_todo_chat_manager = None


def get_todo_chat_manager() -> TodoChatManager:
    """获取待办聊天管理器实例"""
    global _todo_chat_manager
    if _todo_chat_manager is None:
        _todo_chat_manager = TodoChatManager()
    return _todo_chat_manager

