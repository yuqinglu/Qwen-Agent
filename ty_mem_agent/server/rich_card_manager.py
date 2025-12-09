#!/usr/bin/env python3
"""
富媒体卡片管理器
管理待办事项关联的富媒体卡片（天气、导航、打车等）
支持按 event_id 和 card_id 进行存储、查询、更新、删除
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from loguru import logger


# 富媒体卡片类型枚举
CARD_TYPES = [
    "weather",           # 天气卡片
    "navigation",        # 导航卡片
    "ride_hailing",      # 打车卡片
    "hotel",             # 酒店卡片
    "flight",            # 航班卡片
    "train",             # 火车票卡片
    "restaurant",        # 餐厅卡片
    "movie",             # 电影卡片
    "reminder",          # 提醒卡片
    "countdown",         # 倒计时卡片
    "location",          # 位置卡片
    "contact",           # 联系人卡片
    "document",          # 文档卡片
    "link",              # 链接卡片
    "custom"             # 自定义卡片
]


@dataclass
class RichCard:
    """富媒体卡片"""
    card_id: str
    event_id: int  # 关联的待办事件ID
    user_id: int   # calendar_user_id
    card_type: str  # 卡片类型
    title: str      # 卡片标题
    subtitle: Optional[str] = None  # 副标题
    icon: Optional[str] = None      # 图标
    data: Dict[str, Any] = field(default_factory=dict)  # 卡片数据
    source: Optional[str] = None    # 数据来源
    created_at: str = ""
    updated_at: str = ""
    expires_at: Optional[str] = None  # 过期时间
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at
    
    def to_dict(self) -> Dict:
        return {
            "card_id": self.card_id,
            "event_id": self.event_id,
            "user_id": self.user_id,
            "card_type": self.card_type,
            "title": self.title,
            "subtitle": self.subtitle,
            "icon": self.icon,
            "data": self.data,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "RichCard":
        return cls(
            card_id=data["card_id"],
            event_id=data["event_id"],
            user_id=data["user_id"],
            card_type=data["card_type"],
            title=data["title"],
            subtitle=data.get("subtitle"),
            icon=data.get("icon"),
            data=data.get("data", {}),
            source=data.get("source"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            expires_at=data.get("expires_at")
        )


class RichCardManager:
    """富媒体卡片管理器"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RichCardManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # 数据存储路径
        self.data_dir = Path(__file__).parent.parent / "data" / "rich_cards"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 内存缓存
        # cards_by_id: {card_id: RichCard}
        self.cards_by_id: Dict[str, RichCard] = {}
        # cards_by_event: {event_id: {card_id: RichCard}}
        self.cards_by_event: Dict[int, Dict[str, RichCard]] = {}
        
        # 加载已有卡片
        self._load_cards()
        
        self._initialized = True
        logger.info(f"✅ 富媒体卡片管理器初始化完成，数据目录: {self.data_dir}")
    
    def _load_cards(self):
        """从文件加载卡片"""
        try:
            for file_path in self.data_dir.glob("*.json"):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        card = RichCard.from_dict(data)
                        self._add_to_cache(card)
                except Exception as e:
                    logger.warning(f"⚠️ 加载卡片文件失败 {file_path}: {e}")
            
            logger.info(f"📚 已加载 {len(self.cards_by_id)} 个富媒体卡片")
        except Exception as e:
            logger.error(f"❌ 加载卡片失败: {e}")
    
    def _add_to_cache(self, card: RichCard):
        """添加卡片到缓存"""
        self.cards_by_id[card.card_id] = card
        
        if card.event_id not in self.cards_by_event:
            self.cards_by_event[card.event_id] = {}
        self.cards_by_event[card.event_id][card.card_id] = card
    
    def _remove_from_cache(self, card: RichCard):
        """从缓存中移除卡片"""
        if card.card_id in self.cards_by_id:
            del self.cards_by_id[card.card_id]
        
        if card.event_id in self.cards_by_event:
            if card.card_id in self.cards_by_event[card.event_id]:
                del self.cards_by_event[card.event_id][card.card_id]
            # 如果该事件没有卡片了，删除事件索引
            if not self.cards_by_event[card.event_id]:
                del self.cards_by_event[card.event_id]
    
    def _save_card(self, card: RichCard):
        """保存卡片到文件"""
        try:
            file_path = self.data_dir / f"{card.card_id}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(card.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"❌ 保存卡片失败: {e}")
    
    def _delete_card_file(self, card_id: str):
        """删除卡片文件"""
        try:
            file_path = self.data_dir / f"{card_id}.json"
            if file_path.exists():
                file_path.unlink()
        except Exception as e:
            logger.error(f"❌ 删除卡片文件失败: {e}")
    
    def create_card(
        self,
        event_id: int,
        user_id: int,
        card_type: str,
        title: str,
        subtitle: Optional[str] = None,
        icon: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None,
        expires_at: Optional[str] = None,
        card_id: Optional[str] = None
    ) -> RichCard:
        """创建新的富媒体卡片"""
        if card_id is None:
            card_id = f"card_{uuid.uuid4().hex[:12]}"
        
        # 验证卡片类型
        if card_type not in CARD_TYPES:
            logger.warning(f"⚠️ 未知的卡片类型: {card_type}，将使用 'custom'")
            card_type = "custom"
        
        card = RichCard(
            card_id=card_id,
            event_id=event_id,
            user_id=user_id,
            card_type=card_type,
            title=title,
            subtitle=subtitle,
            icon=icon,
            data=data or {},
            source=source,
            expires_at=expires_at
        )
        
        self._add_to_cache(card)
        self._save_card(card)
        
        logger.info(f"✅ 创建富媒体卡片: {card_id}, event_id={event_id}, type={card_type}, title={title}")
        return card
    
    def get_card(self, card_id: str) -> Optional[RichCard]:
        """根据 card_id 获取卡片"""
        return self.cards_by_id.get(card_id)
    
    def get_cards_by_event(
        self,
        event_id: int,
        user_id: Optional[int] = None,
        card_type: Optional[str] = None
    ) -> List[RichCard]:
        """
        根据 event_id 获取关联的所有卡片
        
        Args:
            event_id: 待办事件ID
            user_id: 可选，用于验证权限
            card_type: 可选，过滤卡片类型
            
        Returns:
            卡片列表
        """
        cards = list(self.cards_by_event.get(event_id, {}).values())
        
        # 按用户过滤
        if user_id is not None:
            cards = [c for c in cards if c.user_id == user_id]
        
        # 按类型过滤
        if card_type is not None:
            cards = [c for c in cards if c.card_type == card_type]
        
        # 按更新时间倒序
        cards.sort(key=lambda x: x.updated_at, reverse=True)
        
        return cards
    
    def update_card(
        self,
        card_id: str,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        icon: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None,
        expires_at: Optional[str] = None
    ) -> Optional[RichCard]:
        """更新卡片"""
        card = self.cards_by_id.get(card_id)
        if not card:
            logger.warning(f"⚠️ 卡片不存在: {card_id}")
            return None
        
        # 更新字段
        if title is not None:
            card.title = title
        if subtitle is not None:
            card.subtitle = subtitle
        if icon is not None:
            card.icon = icon
        if data is not None:
            card.data = data
        if source is not None:
            card.source = source
        if expires_at is not None:
            card.expires_at = expires_at
        
        card.updated_at = datetime.now().isoformat()
        
        self._save_card(card)
        
        logger.info(f"✅ 更新富媒体卡片: {card_id}")
        return card
    
    def delete_card(self, card_id: str) -> bool:
        """删除卡片"""
        card = self.cards_by_id.get(card_id)
        if not card:
            logger.warning(f"⚠️ 卡片不存在: {card_id}")
            return False
        
        self._remove_from_cache(card)
        self._delete_card_file(card_id)
        
        logger.info(f"✅ 删除富媒体卡片: {card_id}")
        return True
    
    def delete_cards_by_event(self, event_id: int, user_id: Optional[int] = None) -> int:
        """
        删除某个待办的所有卡片
        
        Args:
            event_id: 待办事件ID
            user_id: 可选，用于验证权限
            
        Returns:
            删除的卡片数量
        """
        cards = self.get_cards_by_event(event_id, user_id)
        count = 0
        
        for card in cards:
            if self.delete_card(card.card_id):
                count += 1
        
        logger.info(f"✅ 删除待办 {event_id} 的 {count} 个富媒体卡片")
        return count
    
    def get_cards_by_type(
        self,
        card_type: str,
        user_id: Optional[int] = None
    ) -> List[RichCard]:
        """
        根据卡片类型获取所有卡片
        
        Args:
            card_type: 卡片类型
            user_id: 可选，用于过滤用户
            
        Returns:
            卡片列表
        """
        cards = [c for c in self.cards_by_id.values() if c.card_type == card_type]
        
        if user_id is not None:
            cards = [c for c in cards if c.user_id == user_id]
        
        cards.sort(key=lambda x: x.updated_at, reverse=True)
        return cards
    
    def get_all_cards(self, user_id: Optional[int] = None) -> List[RichCard]:
        """获取所有卡片"""
        cards = list(self.cards_by_id.values())
        
        if user_id is not None:
            cards = [c for c in cards if c.user_id == user_id]
        
        cards.sort(key=lambda x: x.updated_at, reverse=True)
        return cards
    
    def get_stats(self, user_id: Optional[int] = None) -> Dict[str, Any]:
        """获取统计信息"""
        cards = self.get_all_cards(user_id)
        
        # 按类型统计
        type_counts = {}
        for card in cards:
            type_counts[card.card_type] = type_counts.get(card.card_type, 0) + 1
        
        # 按事件统计
        event_counts = {}
        for card in cards:
            event_counts[card.event_id] = event_counts.get(card.event_id, 0) + 1
        
        return {
            "total_cards": len(cards),
            "cards_by_type": type_counts,
            "cards_by_event": event_counts,
            "total_events_with_cards": len(event_counts)
        }


# 全局实例
_rich_card_manager = None


def get_rich_card_manager() -> RichCardManager:
    """获取富媒体卡片管理器实例"""
    global _rich_card_manager
    if _rich_card_manager is None:
        _rich_card_manager = RichCardManager()
    return _rich_card_manager

