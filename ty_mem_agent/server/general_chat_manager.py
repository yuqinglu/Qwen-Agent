#!/usr/bin/env python3
"""
通用聊天会话管理器
基于 conversation_manager 的通用聊天管理器，集成富媒体卡片支持
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from loguru import logger

from .conversation_manager import (
    ConversationManager, 
    Conversation, 
    ConversationMessage
)


class SessionWrapper:
    """会话包装类，用于兼容性"""
    
    def __init__(self, conversation: Conversation):
        self._conversation = conversation
    
    @property
    def session_id(self) -> str:
        """会话ID（兼容属性）"""
        return self._conversation.conversation_id
    
    @property
    def conversation_id(self) -> str:
        """会话ID（原始属性）"""
        return self._conversation.conversation_id
    
    @property
    def user_id(self) -> int:
        """用户ID（转换为int）"""
        return int(self._conversation.user_id)
    
    @property
    def title(self) -> str:
        return self._conversation.title
    
    @property
    def created_at(self) -> str:
        return self._conversation.created_at
    
    @property
    def updated_at(self) -> str:
        return self._conversation.updated_at
    
    @property
    def messages(self) -> List[ConversationMessage]:
        return self._conversation.messages
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [
                {
                    "message_id": msg.message_id,
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp,
                    "rich_cards": msg.metadata.get("rich_cards", []) if msg.metadata else []
                }
                for msg in self.messages
            ]
        }


class GeneralChatManager:
    """
    通用聊天会话管理器
    
    基于 ConversationManager，添加了：
    1. 富媒体卡片管理（通过 rich_card_manager）
    2. 会话与卡片的关联
    3. 用户ID使用int类型（calendar_user_id）
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # 使用独立的数据目录
        data_dir = Path(__file__).parent.parent / "data" / "general_chat"
        
        # 初始化基础会话管理器
        self.conv_manager = ConversationManager(data_dir=data_dir)
        
        # 会话到卡片ID列表的映射 {session_id: [card_id1, card_id2, ...]}
        self.session_cards: Dict[str, List[str]] = {}
        
        # 打车待确认上下文：预估后、用户确认前 {session_id: pending_ride_dict}
        # pending_ride_dict: estimate_flow_id, from_lng, from_lat, from_name, to_lng, to_lat, to_name, user_phone(可选)
        self.session_pending_ride: Dict[str, Dict[str, Any]] = {}
        
        # 会话最近一次创建的打车订单号 {session_id: order_id}，用于用户说「取消订单」时直接调 MCP
        self.session_last_ride_order_id: Dict[str, str] = {}
        
        self._initialized = True
        logger.info("✅ 通用聊天管理器初始化完成（基于 ConversationManager）")
    
    def create_session(
        self,
        user_id: int,
        title: str = "新对话"
    ) -> SessionWrapper:
        """
        创建新会话
        
        Args:
            user_id: 用户ID（int类型）
            title: 会话标题
            
        Returns:
            新创建的会话包装对象
        """
        # 生成通用聊天的会话ID前缀
        conversation_id = f"gc_{uuid.uuid4().hex[:16]}"
        
        # 委托给 ConversationManager，user_id转为字符串
        conversation = self.conv_manager.create_conversation(
            user_id=str(user_id),
            title=title
        )
        
        # 替换会话ID为通用聊天格式
        old_id = conversation.conversation_id
        conversation.conversation_id = conversation_id
        
        # 更新内部缓存
        self.conv_manager.conversations[conversation_id] = conversation
        if old_id in self.conv_manager.conversations:
            del self.conv_manager.conversations[old_id]
        
        # 初始化卡片列表
        self.session_cards[conversation_id] = []
        
        logger.info(f"✅ 创建通用聊天会话: session_id={conversation_id}, user_id={user_id}")
        return SessionWrapper(conversation)
    
    def get_session(self, session_id: str) -> Optional[SessionWrapper]:
        """获取会话"""
        conversation = self.conv_manager.get_conversation(session_id)
        return SessionWrapper(conversation) if conversation else None
    
    def get_user_sessions(
        self,
        user_id: int,
        limit: int = 50,
        offset: int = 0
    ) -> List[SessionWrapper]:
        """
        获取用户的会话列表
        
        Args:
            user_id: 用户ID
            limit: 返回数量限制
            offset: 偏移量
            
        Returns:
            会话列表（按更新时间倒序）
        """
        # 委托给 ConversationManager
        summaries = self.conv_manager.get_user_conversations(
            user_id=str(user_id),
            limit=limit
        )
        
        # 获取完整的会话对象并包装
        sessions = []
        for summary in summaries[offset:offset + limit]:
            conversation = self.conv_manager.get_conversation(summary['conversation_id'])
            if conversation:
                sessions.append(SessionWrapper(conversation))
        
        return sessions
    
    def update_session_title(self, session_id: str, title: str) -> bool:
        """更新会话标题"""
        return self.conv_manager.update_conversation_title(session_id, title)
    
    def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        # 删除关联的卡片映射
        if session_id in self.session_cards:
            del self.session_cards[session_id]
        
        return self.conv_manager.delete_conversation(session_id)
    
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        rich_cards: Optional[List[Dict]] = None
    ) -> Optional[ConversationMessage]:
        """
        添加消息到会话
        
        Args:
            session_id: 会话ID
            role: 角色 ("user" 或 "assistant")
            content: 消息内容
            rich_cards: 富媒体卡片ID列表（仅AI消息）
            
        Returns:
            新添加的消息
        """
        # 将rich_cards作为metadata存储
        metadata = {"rich_cards": rich_cards} if rich_cards else None
        
        return self.conv_manager.add_message(
            conversation_id=session_id,
            role=role,
            content=content,
            metadata=metadata
        )
    
    def add_card_to_session(
        self,
        session_id: str,
        card: Dict
    ) -> bool:
        """
        添加富媒体卡片到会话（存储卡片ID）
        
        Args:
            session_id: 会话ID
            card: 富媒体卡片数据（包含card_id）
            
        Returns:
            是否成功
        """
        if not self.get_session(session_id):
            logger.warning(f"⚠️ 会话不存在: {session_id}")
            return False
        
        card_id = card.get("card_id")
        if not card_id:
            logger.warning("⚠️ 卡片缺少card_id")
            return False
        
        # 初始化卡片列表
        if session_id not in self.session_cards:
            self.session_cards[session_id] = []
        
        # 检查是否已存在
        if card_id in self.session_cards[session_id]:
            logger.debug(f"⚠️ 卡片已存在: card_id={card_id}")
            return False
        
        # 添加卡片ID
        self.session_cards[session_id].append(card_id)
        
        logger.info(f"✅ 添加卡片到会话: session_id={session_id}, card_id={card_id}")
        return True
    
    def remove_card_from_session(self, session_id: str, card_id: str) -> bool:
        """
        从会话中移除卡片 ID（例如待办被取消后，本地卡片删除时需同步从会话关联中移除）

        Args:
            session_id: 会话 ID
            card_id: 卡片 ID

        Returns:
            是否完成移除（存在则移除并返回 True，不存在则返回 False）
        """
        if not self.get_session(session_id):
            return False
        if session_id not in self.session_cards:
            return False
        lst = self.session_cards[session_id]
        if card_id not in lst:
            return False
        lst.remove(card_id)
        logger.info(f"✅ 从会话移除卡片: session_id={session_id}, card_id={card_id}")
        return True
    
    def get_session_messages(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> Optional[List[ConversationMessage]]:
        """
        获取会话的消息列表
        
        Args:
            session_id: 会话ID
            limit: 返回数量限制
            offset: 偏移量
            
        Returns:
            消息列表，如果会话不存在则返回None
        """
        conversation = self.conv_manager.get_conversation(session_id)
        if not conversation:
            return None
        
        # 分页并返回消息对象
        return conversation.messages[offset:offset + limit]
    
    def get_session_cards(self, session_id: str) -> Optional[List[Dict]]:
        """
        获取会话的富媒体卡片列表
        
        Args:
            session_id: 会话ID
            
        Returns:
            富媒体卡片列表，如果会话不存在则返回None
        """
        if not self.get_session(session_id):
            return None
        
        # 获取该会话关联的卡片ID列表
        card_ids = self.session_cards.get(session_id, [])
        
        # 通过 rich_card_manager 获取完整的卡片信息
        from .rich_card_manager import get_rich_card_manager
        card_manager = get_rich_card_manager()
        
        cards = []
        for card_id in card_ids:
            card = card_manager.get_card(card_id)
            if card:
                cards.append(card.to_dict())
        
        return cards
    
    def set_pending_ride(self, session_id: str, data: Dict[str, Any]) -> None:
        """设置会话的打车待确认上下文（预估后、用户确认叫车前）"""
        self.session_pending_ride[session_id] = dict(data)
        logger.debug(f"✅ 设置 pending_ride: session_id={session_id}")
    
    def get_pending_ride(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取会话的打车待确认上下文，不存在返回 None"""
        return self.session_pending_ride.get(session_id)
    
    def clear_pending_ride(self, session_id: str) -> None:
        """清除会话的打车待确认上下文（叫车成功后或超时）"""
        if session_id in self.session_pending_ride:
            del self.session_pending_ride[session_id]
            logger.debug(f"✅ 清除 pending_ride: session_id={session_id}")

    def set_last_ride_order_id(self, session_id: str, order_id: str) -> None:
        """记录会话下最近创建的打车订单号（用于取消订单时直接调 MCP）"""
        self.session_last_ride_order_id[session_id] = str(order_id)
        logger.debug(f"✅ 记录 last_ride_order_id: session_id={session_id}, order_id={order_id}")

    def get_last_ride_order_id(self, session_id: str) -> Optional[str]:
        """获取会话下最近创建的打车订单号，不存在返回 None"""
        return self.session_last_ride_order_id.get(session_id)

    def clear_last_ride_order_id(self, session_id: str) -> None:
        """取消订单成功后清除会话的最近订单号"""
        if session_id in self.session_last_ride_order_id:
            del self.session_last_ride_order_id[session_id]
            logger.debug(f"✅ 清除 last_ride_order_id: session_id={session_id}")


# 全局单例
_general_chat_manager = None


def get_general_chat_manager() -> GeneralChatManager:
    """获取通用聊天管理器单例"""
    global _general_chat_manager
    if _general_chat_manager is None:
        _general_chat_manager = GeneralChatManager()
    return _general_chat_manager

