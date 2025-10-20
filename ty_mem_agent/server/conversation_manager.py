#!/usr/bin/env python3
"""
会话历史管理模块
负责管理用户的聊天会话历史、消息存储和会话切换
"""

import json
import uuid
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, asdict
from loguru import logger


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
            'conversation_id': self.conversation_id,
            'user_id': self.user_id,
            'title': self.title,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'message_count': len(self.messages),
            'messages': [asdict(msg) for msg in self.messages]
        }
    
    def to_summary(self):
        """转换为摘要（不包含消息内容）"""
        return {
            'conversation_id': self.conversation_id,
            'user_id': self.user_id,
            'title': self.title,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'message_count': len(self.messages),
            'last_message_preview': self.messages[-1].content[:50] if self.messages else ''
        }


class ConversationManager:
    """会话管理器"""
    
    def __init__(self, data_dir: Optional[Path] = None):
        """
        初始化会话管理器
        
        Args:
            data_dir: 数据存储目录，默认为 ty_mem_agent/data/conversations
        """
        if data_dir is None:
            data_dir = Path(__file__).parent.parent / "data" / "conversations"
        
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 内存缓存
        self.conversations: Dict[str, Conversation] = {}
        
        # 加载现有会话
        self._load_conversations()
        
        logger.info(f"📚 会话管理器初始化完成，数据目录: {self.data_dir}")
    
    def _load_conversations(self):
        """从磁盘加载所有会话"""
        try:
            for conv_file in self.data_dir.glob("*.json"):
                try:
                    with open(conv_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    # 重建会话对象
                    conversation = Conversation(
                        conversation_id=data['conversation_id'],
                        user_id=data['user_id'],
                        title=data['title'],
                        created_at=data['created_at'],
                        updated_at=data['updated_at'],
                        messages=[
                            ConversationMessage(**msg) for msg in data.get('messages', [])
                        ]
                    )
                    
                    self.conversations[conversation.conversation_id] = conversation
                    
                except Exception as e:
                    logger.error(f"加载会话文件失败 {conv_file}: {e}")
            
            logger.info(f"✅ 已加载 {len(self.conversations)} 个会话")
            
        except Exception as e:
            logger.error(f"加载会话失败: {e}")
    
    def _save_conversation(self, conversation: Conversation):
        """保存会话到磁盘"""
        try:
            conv_file = self.data_dir / f"{conversation.conversation_id}.json"
            with open(conv_file, 'w', encoding='utf-8') as f:
                json.dump(conversation.to_dict(), f, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"保存会话失败 {conversation.conversation_id}: {e}")
    
    def create_conversation(self, user_id: str, title: str = "新对话") -> Conversation:
        """
        创建新会话
        
        Args:
            user_id: 用户ID
            title: 会话标题
        
        Returns:
            新创建的会话对象
        """
        conversation_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        
        conversation = Conversation(
            conversation_id=conversation_id,
            user_id=user_id,
            title=title,
            created_at=now,
            updated_at=now,
            messages=[]
        )
        
        self.conversations[conversation_id] = conversation
        self._save_conversation(conversation)
        
        logger.info(f"✅ 创建新会话: {conversation_id} - {title}")
        return conversation
    
    def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        """获取指定会话"""
        return self.conversations.get(conversation_id)
    
    def get_user_conversations(self, user_id: str, limit: int = 50) -> List[Dict]:
        """
        获取用户的所有会话列表（摘要）
        
        Args:
            user_id: 用户ID
            limit: 返回的最大数量
        
        Returns:
            会话摘要列表，按更新时间倒序
        """
        user_conversations = [
            conv for conv in self.conversations.values()
            if conv.user_id == user_id
        ]
        
        # 按更新时间排序
        user_conversations.sort(key=lambda x: x.updated_at, reverse=True)
        
        # 返回摘要
        return [conv.to_summary() for conv in user_conversations[:limit]]
    
    def add_message(
        self, 
        conversation_id: str, 
        role: str, 
        content: str,
        metadata: Optional[Dict] = None
    ) -> Optional[ConversationMessage]:
        """
        添加消息到会话
        
        Args:
            conversation_id: 会话ID
            role: 角色 ('user' 或 'assistant')
            content: 消息内容
            metadata: 元数据
        
        Returns:
            添加的消息对象
        """
        conversation = self.conversations.get(conversation_id)
        if not conversation:
            logger.warning(f"会话不存在: {conversation_id}")
            return None
        
        message_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        message = ConversationMessage(
            message_id=message_id,
            role=role,
            content=content,
            timestamp=timestamp,
            metadata=metadata
        )
        
        conversation.messages.append(message)
        conversation.updated_at = timestamp
        
        # 保存到磁盘
        self._save_conversation(conversation)
        
        logger.debug(f"📝 添加消息到会话 {conversation_id}: {role} - {content[:50]}...")
        return message
    
    def update_conversation_title(self, conversation_id: str, title: str) -> bool:
        """
        更新会话标题
        
        Args:
            conversation_id: 会话ID
            title: 新标题
        
        Returns:
            是否成功
        """
        conversation = self.conversations.get(conversation_id)
        if not conversation:
            logger.warning(f"会话不存在: {conversation_id}")
            return False
        
        conversation.title = title
        conversation.updated_at = datetime.now().isoformat()
        
        # 保存到磁盘
        self._save_conversation(conversation)
        
        logger.info(f"✅ 更新会话标题: {conversation_id} -> {title}")
        return True
    
    def delete_conversation(self, conversation_id: str) -> bool:
        """
        删除会话
        
        Args:
            conversation_id: 会话ID
        
        Returns:
            是否成功
        """
        if conversation_id not in self.conversations:
            logger.warning(f"会话不存在: {conversation_id}")
            return False
        
        # 从内存删除
        del self.conversations[conversation_id]
        
        # 从磁盘删除
        try:
            conv_file = self.data_dir / f"{conversation_id}.json"
            if conv_file.exists():
                conv_file.unlink()
            
            logger.info(f"🗑️  删除会话: {conversation_id}")
            return True
            
        except Exception as e:
            logger.error(f"删除会话文件失败: {e}")
            return False
    
    def get_conversation_messages(self, conversation_id: str) -> List[Dict]:
        """
        获取会话的所有消息
        
        Args:
            conversation_id: 会话ID
        
        Returns:
            消息列表
        """
        conversation = self.conversations.get(conversation_id)
        if not conversation:
            return []
        
        return [asdict(msg) for msg in conversation.messages]


# 全局单例
_conversation_manager: Optional[ConversationManager] = None


def get_conversation_manager() -> ConversationManager:
    """获取会话管理器单例"""
    global _conversation_manager
    if _conversation_manager is None:
        _conversation_manager = ConversationManager()
    return _conversation_manager

