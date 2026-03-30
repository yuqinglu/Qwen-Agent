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
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict, field
from loguru import logger


# 富媒体卡片类型枚举
CARD_TYPES = [
    "todo",              # 待办卡片（来自日历 create/update）
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
    "custom",            # 自定义卡片
    "async_task_result"  # 异步任务结果卡片（OpenClaw 执行完成后推送）
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


# ==================== 公共卡片提取工具函数 ====================

def extract_cards_from_ai_response(response_text: str, source: str = "AI响应") -> List[Dict]:
    """
    从AI响应文本中提取富媒体卡片（通过[RICH_CARD]标记）
    
    这是一个公共函数，用于从AI响应中提取[RICH_CARD]标记的卡片信息
    确保通用聊天和待办聊天使用相同的卡片提取逻辑
    
    Args:
        response_text: AI响应文本
        source: 数据来源（默认"AI响应"）
        
    Returns:
        卡片列表，每个卡片包含：card_id, card_type, title, subtitle, icon, data, source, expires_at
    """
    import re
    import json
    
    cards = []
    
    try:
        # 提取[RICH_CARD]标记中的内容
        card_pattern = r'\[RICH_CARD\](.*?)\[/RICH_CARD\]'
        card_matches = re.findall(card_pattern, response_text, re.DOTALL)
        
        for match in card_matches:
            try:
                card_data = json.loads(match.strip())
                if isinstance(card_data, dict):
                    # 构建完整的卡片对象（使用统一的规范化函数）
                    card = normalize_card_data(card_data, source=source)
                    if card:
                        cards.append(card)
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ 无法解析富媒体卡片JSON: {match[:100]}... 错误: {e}")
                continue
                
    except Exception as e:
        logger.debug(f"从AI响应中提取卡片失败（正常，不是所有响应都包含卡片）: {e}")
    
    return cards


def _event_id_from_tool_args(tool_args: Any) -> Optional[int]:
    """从工具调用参数中解析 eventId，支持 arg0 包装或顶层。"""
    if tool_args is None:
        return None
    try:
        if isinstance(tool_args, str):
            obj = json.loads(tool_args) if tool_args.strip().startswith("{") else None
        else:
            obj = tool_args
        if not isinstance(obj, dict):
            return None
        eid = obj.get("eventId") or obj.get("event_id")
        if eid is not None:
            return int(eid) if not isinstance(eid, int) else eid
        arg0 = obj.get("arg0")
        if isinstance(arg0, dict):
            eid = arg0.get("eventId") or arg0.get("event_id")
            if eid is not None:
                return int(eid) if not isinstance(eid, int) else eid
    except Exception:
        pass
    return None


def parse_estimate_flow_id_from_taxi_estimate_result(tool_result: Any) -> Optional[str]:
    """
    从 taxi_estimate 工具返回的文本中解析「预估流程ID」。
    例如：预估流程ID: 0ab76e4c697b2edcff5b04f28e5087b0
    """
    import re
    try:
        text = (tool_result if isinstance(tool_result, str) else json.dumps(tool_result, ensure_ascii=False)) or ""
        m = re.search(r"预估流程ID[：:]\s*([a-fA-F0-9]+)", text)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return None


def parse_estimate_trace_id_from_taxi_estimate_result(tool_result: Any) -> Optional[str]:
    """
    从 taxi_estimate 工具返回的文本中解析「estimate_trace_id」。
    MCP create_order 必填。若返回中无单独 trace_id，可复用 estimate_flow_id。
    支持格式：estimate_trace_id: xxx / 预估.*trace[_\s]*id[：:]\s*xxx / trace_id[：:]\s*xxx
    """
    import re
    try:
        text = (tool_result if isinstance(tool_result, str) else json.dumps(tool_result, ensure_ascii=False)) or ""
        patterns = [
            r"estimate_trace_id[：:\s]+\s*([a-fA-F0-9]+)",
            r"预估[^\n]*trace[_\s]*id[：:\s]+\s*([a-fA-F0-9]+)",
            r"trace_id[：:\s]+\s*([a-fA-F0-9]+)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
    except Exception:
        pass
    return None


def build_ride_hailing_cards_from_didi_result(
    tool_name: str,
    tool_result: Any,
    user_id: int = None,
    user_phone: Optional[str] = None,
    tool_args: Any = None,
) -> Optional[List[Dict]]:
    """
    从滴滴打车 MCP 工具结果构建打车卡片，支持三阶段流程：
    1. 确认订单阶段（taxi_estimate）：生成车型选择卡片（每种车型一张），含起点、终点、价格、车型
    2. 执行订单阶段（taxi_create_order）：生成"正在叫车"通知卡片
    3. 成功阶段（taxi_create_order 成功）：生成订单详情卡片（车辆信息、订单号等）
    
    Args:
        tool_name: 例如 Didi-Ride-taxi_estimate, Didi-Ride-taxi_create_order
        tool_result: 工具返回结果（str 或 dict）
        user_id: calendar_user_id
        user_phone: 用户电话号码（可选），如果有则在确认订单卡片中包含
        tool_args: taxi_estimate 调用时的参数（str 或 dict），用于解析 from_name, to_name 等，便于卡片展示起点终点
        
    Returns:
        卡片列表（可能为空），非滴滴打车工具或无法解析时返回 None
    """
    if not tool_name or not str(tool_name).startswith("Didi-Ride-"):
        return None
    
    name = str(tool_name).replace("Didi-Ride-", "")
    cards = []
    
    # 从 tool_args 解析起点、终点（taxi_estimate 参数）
    origin_name = None
    destination_name = None
    origin_coords = None
    destination_coords = None
    if tool_args is not None:
        try:
            args = tool_args if isinstance(tool_args, dict) else json.loads(str(tool_args))
            if isinstance(args, dict):
                origin_name = args.get("from_name")
                destination_name = args.get("to_name")
                if args.get("from_lng") is not None and args.get("from_lat") is not None:
                    origin_coords = {"lng": float(args["from_lng"]), "lat": float(args["from_lat"])}
                if args.get("to_lng") is not None and args.get("to_lat") is not None:
                    destination_coords = {"lng": float(args["to_lng"]), "lat": float(args["to_lat"])}
        except Exception:
            pass
    
    try:
        # 解析工具结果（taxi_estimate 常返回纯文本，不是 JSON）
        if isinstance(tool_result, dict):
            obj = tool_result
        elif isinstance(tool_result, str):
            obj = json.loads(tool_result) if tool_result.strip().startswith(("{", "[")) else None
        else:
            obj = None
        
        # 阶段1：价格预估（taxi_estimate）- 生成车型选择卡片（支持纯文本返回）
        if name == "taxi_estimate":
            # 使用原始字符串解析，不依赖 obj（MCP 常返回多行文本）
            result_text = str(tool_result) if tool_result else ""
            if isinstance(tool_result, dict):
                result_text = json.dumps(tool_result, ensure_ascii=False)
            
            import re
            # 查找【用户显示内容】部分（如果存在）
            user_content_match = re.search(r'【用户显示内容】\s*\n(.*?)(?:\n\n|$)', result_text, re.DOTALL)
            if user_content_match:
                result_text = user_content_match.group(1)
            
            # 查找"网约车价格预估结果："后的内容
            price_section_match = re.search(r'网约车价格预估结果[：:]\s*\n(.*?)(?:\n\n|预估流程ID|$)', result_text, re.DOTALL)
            if price_section_match:
                result_text = price_section_match.group(1)
            
            lines = result_text.split('\n')
            for line in lines:
                line = line.strip()
                if not line or not re.match(r'^\d+\.', line):
                    continue
                
                # 匹配格式：1. 特惠快车: 约 10 元 (品类代码: 201) 或 1. 特惠快车 (product_category: 201)
                match = re.match(r'^\d+\.\s*(.+?)(?:\s*[:：]\s*约\s*(\d+)\s*元)?\s*\([^)]*[品类代码product_category:：\s]*(\d+)\)', line)
                if match:
                    vehicle_type = match.group(1).strip()
                    price = match.group(2) if match.group(2) else None
                    category_code = int(match.group(3))
                    
                    card_id = f"ride_option_{category_code}_{uuid.uuid4().hex[:8]}"
                    subtitle_parts = []
                    if origin_name and destination_name:
                        subtitle_parts.append(f"{origin_name} → {destination_name}")
                    if price:
                        subtitle_parts.append(f"约{price}元")
                    if user_phone:
                        subtitle_parts.append(f"电话: {user_phone}")
                    
                    data = {
                        "vehicle_type": vehicle_type,
                        "product_category": category_code,
                        "estimated_price": price,
                        "phone": user_phone,
                        "stage": "confirm",
                    }
                    if origin_name is not None:
                        data["origin"] = origin_name
                    if destination_name is not None:
                        data["destination"] = destination_name
                    if origin_coords:
                        data["origin_coords"] = origin_coords
                    if destination_coords:
                        data["destination_coords"] = destination_coords
                    
                    card = {
                        "card_id": card_id,
                        "card_type": "ride_hailing",
                        "title": vehicle_type,
                        "subtitle": " | ".join(subtitle_parts) if subtitle_parts else "点击选择",
                        "icon": "🚕",
                        "data": data,
                        "source": tool_name,
                        "created_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat(),
                        "expires_at": None,
                    }
                    cards.append(card)
            
            return cards if cards else None
        
        # 仅当非 taxi_create_order 且无 obj 时提前返回（taxi_create_order 可用纯文本）
        if obj is None and name != "taxi_create_order":
            return None

        # 阶段2和3：创建订单（taxi_create_order）
        if name == "taxi_create_order":
            result_text = str(tool_result) if tool_result else ""
            if isinstance(tool_result, dict):
                result_text = json.dumps(tool_result, ensure_ascii=False)
            elif obj is not None:
                result_text = json.dumps(obj, ensure_ascii=False)
            
            # 检查是否成功
            if "订单创建成功" in result_text or "订单号" in result_text:
                # 阶段3：成功 - 提取订单信息
                import re
                
                # 提取订单号
                order_match = re.search(r'订单号[：:]\s*([A-Za-z0-9]+)', result_text)
                order_id = order_match.group(1) if order_match else None
                
                # 提取起点和终点（支持全角括号 （） 与半角 ()）
                origin_match = re.search(r'起点[：:]\s*([^（(]+)[（(]([^）)]+)[）)]', result_text)
                dest_match = re.search(r'终点[：:]\s*([^（(]+)[（(]([^）)]+)[）)]', result_text)
                
                origin_name = origin_match.group(1).strip() if origin_match else None
                origin_coords = origin_match.group(2) if origin_match else None
                dest_name = dest_match.group(1).strip() if dest_match else None
                dest_coords = dest_match.group(2) if dest_match else None
                
                # 提取状态
                status_match = re.search(r'状态[：:]\s*(\w+)', result_text)
                status = status_match.group(1) if status_match else "created"
                
                card_id = f"ride_order_{order_id or uuid.uuid4().hex[:12]}"
                card = {
                    "card_id": card_id,
                    "card_type": "ride_hailing",
                    "title": "订单创建成功" if status == "created" else "订单信息",
                    "subtitle": f"订单号: {order_id}，正在等待司机接单" if order_id else "正在为您叫车",
                    "icon": "🚕",
                    "data": {
                        "order_id": order_id,
                        "origin": origin_name,
                        "origin_coords": origin_coords,
                        "destination": dest_name,
                        "dest_coords": dest_coords,
                        "status": status,
                        "stage": "success",  # 成功阶段
                    },
                    "source": tool_name,
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "expires_at": None,
                }
                cards.append(card)
            else:
                # 阶段2：执行中 - 生成"正在叫车"通知卡片
                card_id = f"ride_executing_{uuid.uuid4().hex[:12]}"
                card = {
                    "card_id": card_id,
                    "card_type": "ride_hailing",
                    "title": "正在为您叫车",
                    "subtitle": "请稍候...",
                    "icon": "🚕",
                    "data": {
                        "stage": "executing",  # 执行阶段
                    },
                    "source": tool_name,
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "expires_at": None,
                }
                cards.append(card)
            
            return cards if cards else None
        
        return None
        
    except Exception as e:
        logger.debug(f"解析滴滴打车工具结果失败: {e}")
        return None


def _parse_driver_query_info(query_result: Any) -> Optional[Dict]:
    """
    从 taxi_query_order 返回结果解析所有司机/行程字段，供各阶段卡片构建函数共用。

    返回字段：
        driver_name, car_model, car_plate, driver_phone,
        distance_km, eta_minutes,
        is_arrived (bool) — 是否检测到「司机已到达」信号
    无法解析到任何司机信息时返回 None。
    """
    import re

    if query_result is None:
        return None

    text = (
        str(query_result)
        if not isinstance(query_result, dict)
        else json.dumps(query_result, ensure_ascii=False)
    )
    obj = query_result if isinstance(query_result, dict) else None
    if obj is None and isinstance(query_result, str) and query_result.strip().startswith(("{", "[")):
        try:
            obj = json.loads(query_result)
        except Exception:
            pass

    driver_name = car_model = car_plate = driver_phone = None
    distance_km = eta_minutes = None

    if obj and isinstance(obj, dict):
        driver_name = obj.get("driver_name") or obj.get("driverName") or obj.get("司机") or obj.get("称呼")
        car_model = obj.get("car_model") or obj.get("carModel") or obj.get("车型") or obj.get("vehicle_info")
        car_plate = obj.get("car_plate") or obj.get("carPlate") or obj.get("车牌")
        driver_phone = obj.get("driver_phone") or obj.get("driverPhone") or obj.get("电话")
        distance_km = obj.get("distance_km") or obj.get("distanceKm")
        eta_minutes = obj.get("eta_minutes") or obj.get("etaMinutes")

    # 从纯文本解析（MCP 常返回多行文本）
    if not (driver_name and car_plate and driver_phone and car_model):
        if not driver_name:
            m = re.search(r"称呼[：:]\s*([^\n•]+)", text)
            if m:
                driver_name = m.group(1).strip()
        if not driver_name:
            m = re.search(r"司机[：:]\s*([^\n•]+)", text)
            if m:
                driver_name = m.group(1).strip()
        if not car_model:
            m = re.search(r"车型[：:]\s*([^\n•]+)", text)
            if m:
                car_model = m.group(1).strip()
        if not car_plate:
            m = re.search(r"车牌[：:]\s*([^\n•]+)", text)
            if m:
                car_plate = m.group(1).strip()
        if not driver_phone:
            m = re.search(r"[•\s]电话[：:]\s*([^\n]+)", text)
            if m:
                driver_phone = m.group(1).strip()
            if not driver_phone:
                m = re.search(r"(?:司机)?电话[：:]\s*([^\s\n]+)", text)
                if m:
                    driver_phone = m.group(1).strip()
            if not driver_phone:
                for m in re.finditer(r"1[3-9]\d{9}", text):
                    driver_phone = m.group(0)
                    break
        if distance_km is None:
            m = re.search(r"(?:离上车点)?还有[：:]\s*([\d.]+)\s*公里", text)
            if m:
                try:
                    distance_km = float(m.group(1))
                except ValueError:
                    distance_km = m.group(1)
        if eta_minutes is None:
            m = re.search(r"约需\s*(\d+)\s*分钟", text)
            if m:
                try:
                    eta_minutes = int(m.group(1))
                except ValueError:
                    eta_minutes = m.group(1)

    if not driver_name and not car_plate and not driver_phone:
        return None

    # 检测「司机已到达」信号
    _arrived_patterns = ("已到达", "已抵达", "等待乘客", "到达上车点", "到达起点", "driver arrived", "已到上车点")
    is_arrived = any(p in text for p in _arrived_patterns)

    return {
        "driver_name": driver_name,
        "car_model": car_model,
        "car_plate": car_plate,
        "driver_phone": driver_phone,
        "distance_km": distance_km,
        "eta_minutes": eta_minutes,
        "is_arrived": is_arrived,
    }


def is_taxi_query_order_cancelled_result(text: str) -> bool:
    """
    判断 taxi_query_order 返回文案是否表示订单已取消（含用户在其他端取消）。
    规则偏保守，避免误伤普通对话文案。
    """
    if not text or not str(text).strip():
        return False
    t = str(text).strip()
    if "订单已取消" in t:
        return True
    if "已取消" in t:
        hints = ("退款", "费用", "到账", "重新叫车", "原支付")
        if any(h in t for h in hints):
            return True
    return False


def build_driver_card_from_query_result(
    order_id: str,
    query_result: Any,
) -> Optional[Dict]:
    """
    从 taxi_query_order 结果构建「司机已接单」卡片（stage: driver_assigned）。

    示例文本：
      司机信息：
      • 称呼：体验模式司机
      • 车型：黑 · 奥迪 · A6
      • 车牌：京TEST2025
      • 电话：0000000000
      师傅离上车点还有：2.5 公里，约需8分钟到达。
    """
    if not order_id:
        return None
    info = _parse_driver_query_info(query_result)
    if not info:
        return None

    subtitle_parts = []
    if info["driver_name"]:
        subtitle_parts.append(info["driver_name"])
    if info["car_model"]:
        subtitle_parts.append(info["car_model"])
    if info["car_plate"]:
        subtitle_parts.append(f"车牌 {info['car_plate']}")
    if info["driver_phone"]:
        subtitle_parts.append(f"电话 {info['driver_phone']}")
    if info["distance_km"] is not None:
        subtitle_parts.append(f"{info['distance_km']} 公里")
    if info["eta_minutes"] is not None:
        subtitle_parts.append(f"约 {info['eta_minutes']} 分钟到达")

    data: Dict[str, Any] = {
        "order_id": order_id,
        "stage": "driver_assigned",
        "driver_name": info["driver_name"],
        "car_plate": info["car_plate"],
        "driver_phone": info["driver_phone"],
    }
    if info["car_model"] is not None:
        data["car_model"] = info["car_model"]
    if info["distance_km"] is not None:
        data["distance_km"] = info["distance_km"]
    if info["eta_minutes"] is not None:
        data["eta_minutes"] = info["eta_minutes"]

    return {
        "card_id": f"ride_driver_{order_id}_{uuid.uuid4().hex[:6]}",
        "card_type": "ride_hailing",
        "title": "司机已接单",
        "subtitle": " | ".join(subtitle_parts) if subtitle_parts else "可查看司机与车辆信息",
        "icon": "🚕",
        "data": data,
        "source": "Didi-Ride-taxi_query_order",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "expires_at": None,
    }


def build_driver_approaching_card(
    order_id: str,
    query_result: Any,
) -> Optional[Dict]:
    """
    从 taxi_query_order 结果构建「司机即将到达」卡片（stage: driver_approaching）。

    仅当能解析到 eta_minutes 或 distance_km 时才构建，由调用方控制只推送一次。
    """
    if not order_id:
        return None
    info = _parse_driver_query_info(query_result)
    if not info:
        return None
    if info["eta_minutes"] is None and info["distance_km"] is None:
        return None

    subtitle_parts = []
    if info["eta_minutes"] is not None:
        subtitle_parts.append(f"预计 {info['eta_minutes']} 分钟后到达")
    if info["distance_km"] is not None:
        subtitle_parts.append(f"距起点 {info['distance_km']} 公里")
    if info["driver_name"]:
        subtitle_parts.append(info["driver_name"])
    if info["car_plate"]:
        subtitle_parts.append(f"车牌 {info['car_plate']}")

    data: Dict[str, Any] = {
        "order_id": order_id,
        "stage": "driver_approaching",
        "driver_name": info["driver_name"],
        "car_plate": info["car_plate"],
        "driver_phone": info["driver_phone"],
    }
    if info["car_model"] is not None:
        data["car_model"] = info["car_model"]
    if info["distance_km"] is not None:
        data["distance_km"] = info["distance_km"]
    if info["eta_minutes"] is not None:
        data["eta_minutes"] = info["eta_minutes"]

    return {
        "card_id": f"ride_approaching_{order_id}_{uuid.uuid4().hex[:6]}",
        "card_type": "ride_hailing",
        "title": "司机即将到达",
        "subtitle": " | ".join(subtitle_parts) if subtitle_parts else "司机正在赶来",
        "icon": "🚗",
        "data": data,
        "source": "Didi-Ride-taxi_query_order",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "expires_at": None,
    }


def build_driver_arrived_card(
    order_id: str,
    query_result: Any,
) -> Optional[Dict]:
    """
    从 taxi_query_order 结果构建「司机已到达起点」卡片（stage: driver_arrived）。

    仅当检测到「到达」信号（已到达/已抵达/等待乘客等）时才构建。
    """
    if not order_id:
        return None
    info = _parse_driver_query_info(query_result)
    if not info or not info["is_arrived"]:
        return None

    subtitle_parts = []
    if info["driver_name"]:
        subtitle_parts.append(info["driver_name"])
    if info["car_plate"]:
        subtitle_parts.append(f"车牌 {info['car_plate']}")
    if info["driver_phone"]:
        subtitle_parts.append(f"电话 {info['driver_phone']}")

    data: Dict[str, Any] = {
        "order_id": order_id,
        "stage": "driver_arrived",
        "driver_name": info["driver_name"],
        "car_plate": info["car_plate"],
        "driver_phone": info["driver_phone"],
    }
    if info["car_model"] is not None:
        data["car_model"] = info["car_model"]

    return {
        "card_id": f"ride_arrived_{order_id}_{uuid.uuid4().hex[:6]}",
        "card_type": "ride_hailing",
        "title": "司机已到达起点",
        "subtitle": " | ".join(subtitle_parts) if subtitle_parts else "请出发上车",
        "icon": "📍",
        "data": data,
        "source": "Didi-Ride-taxi_query_order",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "expires_at": None,
    }


def build_todo_card_from_calendar_result(
    tool_name: str,
    tool_result: Any,
    user_id: int = None,
    tool_args: Any = None,
) -> Optional[Tuple[Optional[Dict], int, str]]:
    """
    从日历 MCP 工具结果构建待办卡片信息，供通用聊天 WebSocket 创建、更新或删除本地卡片。
    不负责实际落库，只返回 (card_dict, event_id, action)。

    Args:
        tool_name: 例如 calendar-service-createOneTimeEvent
        tool_result: 工具返回（str 或 dict，成功结果通常含 event 或 event.id）
        user_id: calendar_user_id，用于卡片归属
        tool_args: 工具调用参数（dict 或 JSON str），cancel 时结果无 eventId 时从此解析

    Returns:
        (card_dict 或 None, event_id, "create"|"update"|"delete")；delete 时 card_dict 为 None。
        非日历工具或无法解析时返回 None。
    """
    if not tool_name or not str(tool_name).startswith("calendar-service-"):
        return None
    name = str(tool_name).replace("calendar-service-", "")
    event = None
    event_id = None
    try:
        if isinstance(tool_result, dict):
            obj = tool_result
        elif isinstance(tool_result, str):
            obj = json.loads(tool_result) if tool_result.strip().startswith("{") else None
        else:
            obj = None
        if not isinstance(obj, dict):
            obj = {}
        if "event" in obj:
            event = obj["event"]
        elif obj.get("id") is not None and ("title" in obj or "eventDate" in obj):
            event = obj
        if isinstance(event, dict):
            eid = event.get("id")
            if eid is not None:
                event_id = int(eid) if not isinstance(eid, int) else eid
        if event_id is None:
            event_id = obj.get("eventId") or obj.get("event_id")
            if event_id is not None:
                event_id = int(event_id) if not isinstance(event_id, int) else event_id
        if event_id is None and name.startswith("cancel"):
            event_id = _event_id_from_tool_args(tool_args)
    except Exception as e:
        logger.debug(f"解析日历工具结果失败: {e}")
        return None
    if event_id is None and name not in ("cancelOneTimeEventInstance", "cancelRecurringEventInstance"):
        return None
    if name in ("createOneTimeEvent", "createRecurringEvent"):
        action = "create"
    elif name.startswith("modify") or name.startswith("modifyAll"):
        action = "update"
    elif name.startswith("cancel"):
        action = "delete"
        if event_id is None:
            return None
        return (None, event_id, action)
    else:
        return None
    # build card dict for create/update
    title = event.get("title") or "待办"
    subtitle = event.get("location") or (event.get("description") or "")[:80]
    if subtitle and len((event.get("description") or "")) > 80:
        subtitle = subtitle + "..."
    card_id = f"todo_{event_id}"
    card = {
        "card_id": card_id,
        "card_type": "todo",
        "title": title,
        "subtitle": subtitle or None,
        "icon": "📌",
        "data": dict(event),
        "source": tool_name,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "expires_at": None,
    }
    return (card, event_id, action)


def extract_cards_from_tool_result(tool_name: str, tool_result: str, user_id: int = None) -> List[Dict]:
    """
    从工具调用结果中提取富媒体卡片
    
    这是一个公共函数，用于从工具返回的JSON数据中提取卡片信息
    确保通用聊天和待办聊天使用相同的卡片提取逻辑
    
    Args:
        tool_name: 工具名称
        tool_result: 工具返回的结果（可能是JSON字符串或普通文本）
        user_id: 用户ID（可选，用于生成card_id）
        
    Returns:
        卡片列表，每个卡片包含：card_id, card_type, title, subtitle, icon, data, source, expires_at
    """
    import re
    import json
    from datetime import datetime
    
    # 过滤掉地图搜索工具的POI结果，避免生成大量无关卡片
    # 包括：Didi-Ride-maps_textsearch, amap_maps-maps_text_search, amap_maps-maps_search_detail
    def _is_maps_poi_tool(tn):
        if not tn:
            return False
        tn = str(tn).strip()
        return "maps_textsearch" in tn or "maps_text_search" in tn or "maps_search_detail" in tn

    if _is_maps_poi_tool(tool_name):
        return []

    def _is_poi_only(data):
        """单条 POI 数据（amap 等）：有 id/name/address 或 typecode，且无 weather/route 等业务字段"""
        if not isinstance(data, dict):
            return False
        has_poi = ("id" in data or "name" in data) and ("address" in data or "typecode" in data)
        has_business = any(k in data for k in ("weather", "temperature", "route", "pois", "suggestion"))
        return has_poi and not has_business

    def _should_skip_poi(data, tn):
        return _is_poi_only(data) and _is_maps_poi_tool(tn)

    cards = []

    try:
        # 处理ContentItem列表（QwenAgent工具返回格式）
        if isinstance(tool_result, list):
            for item in tool_result:
                if hasattr(item, 'text'):
                    item_text = item.text
                    if isinstance(item_text, str):
                        try:
                            data = json.loads(item_text)
                            if isinstance(data, dict) and not _should_skip_poi(data, tool_name):
                                card = _build_card_from_data(data, tool_name, user_id)
                                if card:
                                    cards.append(card)
                        except json.JSONDecodeError:
                            json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
                            for match in re.findall(json_pattern, item_text):
                                try:
                                    data = json.loads(match)
                                    if isinstance(data, dict) and not _should_skip_poi(data, tool_name):
                                        card = _build_card_from_data(data, tool_name, user_id)
                                        if card:
                                            cards.append(card)
                                except json.JSONDecodeError:
                                    continue
                elif isinstance(item, dict) and not _should_skip_poi(item, tool_name):
                    card = _build_card_from_data(item, tool_name, user_id)
                    if card:
                        cards.append(card)
        elif isinstance(tool_result, str):
            json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
            for match in re.findall(json_pattern, tool_result):
                try:
                    data = json.loads(match)
                    if isinstance(data, dict) and not _should_skip_poi(data, tool_name):
                        card = _build_card_from_data(data, tool_name, user_id)
                        if card:
                            cards.append(card)
                except json.JSONDecodeError:
                    continue
        elif isinstance(tool_result, dict) and not _should_skip_poi(tool_result, tool_name):
            card = _build_card_from_data(tool_result, tool_name, user_id)
            if card:
                cards.append(card)
                        
    except Exception as e:
        logger.debug(f"从工具结果中提取卡片失败（正常，不是所有工具都返回卡片）: {e}")
    
    return cards


def normalize_card_data(card_data: Dict, source: str = "unknown", user_id: int = None) -> Optional[Dict]:
    """
    规范化卡片数据，确保字段完整且格式统一
    
    这是统一的卡片数据规范化函数，确保所有来源的卡片数据格式一致
    与APP_API_DESIGN中的卡片字段格式保持一致
    
    Args:
        card_data: 原始卡片数据（可能来自AI响应或工具结果）
        source: 数据来源
        user_id: 用户ID（可选）
        
    Returns:
        规范化后的卡片字典，包含以下字段：
        - card_id: 卡片唯一标识
        - card_type: 卡片类型
        - title: 卡片标题
        - subtitle: 副标题（可选）
        - icon: 图标（可选）
        - data: 卡片数据（JSON对象）
        - source: 数据来源
        - created_at: 创建时间
        - updated_at: 更新时间
        - expires_at: 过期时间（可选）
        
        如果数据不符合卡片格式则返回None
    """
    from datetime import datetime
    import uuid
    
    # 如果已经有完整的卡片结构（来自AI的[RICH_CARD]标记），直接规范化
    if 'card_type' in card_data and 'title' in card_data:
        # 确保有card_id
        if 'card_id' not in card_data or not card_data['card_id']:
            card_data['card_id'] = f"card_{uuid.uuid4().hex[:12]}"
        
        # 确保有data字段
        if 'data' not in card_data:
            # 如果没有data字段，将整个card_data作为data（除了元数据字段）
            metadata_fields = {'card_id', 'card_type', 'title', 'subtitle', 'icon', 'source', 'created_at', 'updated_at', 'expires_at'}
            card_data['data'] = {k: v for k, v in card_data.items() if k not in metadata_fields}
        
        # 确保有source
        if 'source' not in card_data or not card_data['source']:
            card_data['source'] = source
        
        # 确保有时间戳
        if 'created_at' not in card_data or not card_data['created_at']:
            card_data['created_at'] = datetime.now().isoformat()
        if 'updated_at' not in card_data or not card_data['updated_at']:
            card_data['updated_at'] = card_data['created_at']
        
        # 确保字段类型正确
        if 'subtitle' not in card_data:
            card_data['subtitle'] = None
        if 'icon' not in card_data:
            card_data['icon'] = None
        if 'expires_at' not in card_data:
            card_data['expires_at'] = None
        
        return card_data
    
    # 否则，从数据中推断卡片信息（来自工具结果）
    return _build_card_from_data(card_data, source, user_id)


def _normalize_card_data(card_data: Dict, source: str = "unknown", user_id: int = None) -> Optional[Dict]:
    """内部函数，调用normalize_card_data（保持向后兼容）"""
    return normalize_card_data(card_data, source, user_id)


def _pick_forecast_index_by_llm(user_query: str, forecasts: List[Dict[str, Any]]) -> Optional[int]:
    """
    使用小模型根据用户问题在多天预报中选择最匹配的一天索引，避免依赖易碎的正则/关键词规则。
    仅传递日期等必要信息，控制 token 量。
    """
    try:
        q = (user_query or "").strip()
        if not q or not forecasts:
            return None

        # 构造简短的日期列表，供模型选择
        items: List[str] = []
        for i, f in enumerate(forecasts):
            date_str = (f.get("date") or "").strip()
            # 兼容部分嵌套在 casts[0].date 的格式
            if not date_str:
                casts = f.get("casts") or []
                if isinstance(casts, list) and casts:
                    date_str = (casts[0].get("date") or "").strip()
            items.append(f"{i}: {date_str or '未知日期'}")
        dates_block = "\n".join(items)

        # 延用现有 LLM 配置，规划/路由类任务使用 qwen-plus 降低成本
        from ty_mem_agent.config.settings import get_llm_config
        from qwen_agent.llm import get_chat_model
        from qwen_agent.llm.schema import Message, USER, SYSTEM

        llm_config = get_llm_config()
        if llm_config.get("model_type") == "qwen_dashscope":
            llm_config = {**llm_config, "model": "qwen-plus"}
        llm = get_chat_model(llm_config)

        today_str = datetime.now().date().isoformat()
        system_prompt = (
            "你是一个助手，根据用户的自然语言问题和给定的天气预报日期列表，"
            "选出最符合用户问题的一天的索引（0 开始）。"
            "要理解相对日期（如今天、明天、后天、本周五、本周末、this Friday、tomorrow 等），"
            "根据今天的日期推断是哪一天，然后在列表中选出对应日期的索引。"
            "只需要在输出中返回一个阿拉伯数字索引，不要返回其他文字。"
        )
        user_content = (
            f"今天日期是：{today_str}。\n"
            f"用户的问题是：「{q}」。\n"
            f"可选的预报日期列表如下（格式：索引: 日期）：\n{dates_block}\n\n"
            f"请你根据用户的问题和今天日期，在上面的列表中选出最合适的一天，"
            f"只输出对应的索引数字（0 到 {len(forecasts) - 1}），不要输出其他任何内容。"
        )

        response_text = ""
        for responses in llm.chat(
            messages=[
                Message(role=SYSTEM, content=system_prompt),
                Message(role=USER, content=user_content),
            ],
            stream=False,
        ):
            if not responses:
                continue
            last = responses[-1] if isinstance(responses, list) else responses
            if hasattr(last, "content") and last.content:
                response_text = last.content if isinstance(last.content, str) else str(last.content)
                break

        if not response_text:
            return None

        # 提取第一个连续数字串作为索引（避免直接依赖正则）
        digits = ""
        for ch in response_text.strip():
            if ch.isdigit():
                digits += ch
            elif digits:
                break
        if not digits:
            return None
        idx = int(digits)
        if 0 <= idx < len(forecasts):
            return idx
        return None
    except Exception as e:
        logger.debug(f"通过 LLM 选择天气预报日期失败: {e}")
        return None


def build_weather_card_from_amap_result(
    tool_name: str,
    tool_result: Any,
    user_id: int = None,
    user_query: Optional[str] = None,
) -> Optional[Dict]:
    """
    从高德天气 MCP 工具结果（amap_maps-maps_weather）构建天气富媒体卡片。
    支持实时天气（lives）与预报（forecasts/casts）格式，归一化为 _build_card_from_data 所需字段。
    """
    if not tool_name or "weather" not in tool_name.lower():
        return None
    try:
        if isinstance(tool_result, str):
            s = tool_result.strip()
            if s.startswith(("{", "[")):
                data = json.loads(s)
            else:
                data = None
        else:
            data = tool_result if isinstance(tool_result, dict) else None
        if not data or not isinstance(data, dict):
            return None
        # 高德实时天气：lives
        if "lives" in data and isinstance(data["lives"], list) and len(data["lives"]) > 0:
            live = data["lives"][0]
            city = live.get("city") or live.get("province") or ""
            if live.get("province") and live.get("city") and live.get("city") != live.get("province"):
                city = f"{live.get('province')}{live.get('city')}"
            reporttime = live.get("reporttime", "")
            flat = {
                "city": city,
                "weather": live.get("weather", ""),
                "temperature": live.get("temperature", ""),
                "winddirection": live.get("winddirection", ""),
                "windpower": live.get("windpower", ""),
                "humidity": live.get("humidity", ""),
                "date": reporttime[:10] if reporttime else "",
                "reporttime": reporttime,
            }
            return _build_card_from_data(flat, tool_name, user_id)
        # 高德预报：forecasts 为每日对象数组（顶层 city，forecasts[].date/dayweather/daytemp 等）
        if "forecasts" in data and isinstance(data["forecasts"], list) and len(data["forecasts"]) > 0:
            city = data.get("city") or ""
            forecasts = data["forecasts"]

            # 默认使用第 1 天；若提供了用户问题，则通过小模型在 forecasts 中选择最匹配的一天
            first = forecasts[0]
            if user_query:
                idx = _pick_forecast_index_by_llm(user_query, forecasts)
                if idx is not None and 0 <= idx < len(forecasts):
                    first = forecasts[idx]

            # 格式1：forecasts[i] 直接是某日（含 dayweather/date）
            if "dayweather" in first or "date" in first:
                dayweather = first.get("dayweather", "")
                nightweather = first.get("nightweather", "")
                weather = dayweather or nightweather
                daytemp = first.get("daytemp", "")
                nighttemp = first.get("nighttemp", "")
                temperature = f"{nighttemp}~{daytemp}℃" if (nighttemp and daytemp) else (f"{daytemp or nighttemp}℃" if (daytemp or nighttemp) else "")
                flat = {
                    "city": city,
                    "weather": weather,
                    "dayweather": dayweather,
                    "nightweather": nightweather,
                    "temperature": temperature,
                    "daytemp": daytemp,
                    "nighttemp": nighttemp,
                    "date": first.get("date", ""),
                    "week": first.get("week", ""),
                }
                return _build_card_from_data(flat, tool_name, user_id)
            # 格式2：forecasts[0].casts 嵌套（部分接口）
            casts = first.get("casts") or []
            if casts:
                cast = casts[0]
                dayweather = cast.get("dayweather", "")
                nightweather = cast.get("nightweather", "")
                weather = dayweather or nightweather
                daytemp = cast.get("daytemp", "")
                nighttemp = cast.get("nighttemp", "")
                temperature = f"{nighttemp}~{daytemp}" if (nighttemp and daytemp) else (daytemp or nighttemp)
                flat = {
                    "city": city,
                    "weather": weather,
                    "dayweather": dayweather,
                    "nightweather": nightweather,
                    "temperature": temperature,
                    "daytemp": daytemp,
                    "nighttemp": nighttemp,
                    "date": cast.get("date", ""),
                    "week": cast.get("week", ""),
                }
                return _build_card_from_data(flat, tool_name, user_id)
        return None
    except Exception as e:
        logger.debug(f"构建天气卡片失败: {e}")
        return None


def _build_card_from_data(data: Dict, tool_name: str, user_id: int = None) -> Optional[Dict]:
    """
    从数据字典构建卡片对象
    
    Args:
        data: 数据字典
        tool_name: 工具名称
        user_id: 用户ID
        
    Returns:
        卡片字典，如果数据不符合卡片格式则返回None
    """
    from datetime import datetime
    
    # 检查是否包含卡片相关的字段
    card_indicators = [
        'weather', 'temperature', 'city', 'location', 'name', 'address', 
        'price', 'route', 'distance', 'duration', 'hotel', 'room', 
        'flight', 'airline', 'departure', 'train', 'restaurant', 'movie'
    ]
    
    if not any(key in data for key in card_indicators):
        return None
    
    # 推断卡片类型
    card_type = _infer_card_type(data)
    
    # 推断标题
    title = _infer_card_title(data, tool_name)
    
    # 生成card_id
    import uuid
    card_id = f"card_{uuid.uuid4().hex[:12]}"
    
    # 构建卡片对象（与app_api_routes中的格式一致）
    card = {
        "card_id": card_id,
        "card_type": card_type,
        "title": title,
        "subtitle": _infer_card_subtitle(data),
        "icon": _infer_card_icon(card_type),
        "data": data,
        "source": tool_name,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "expires_at": _infer_card_expires_at(data, card_type)
    }
    
    return card


def _infer_card_type(data: Dict) -> str:
    """根据数据内容推断卡片类型"""
    if any(k in data for k in ['weather', 'temperature', 'dayweather', 'nightweather']):
        return 'weather'
    elif any(k in data for k in ['route', 'distance', 'duration', 'waypoints']):
        return 'navigation'
    elif any(k in data for k in ['ride', 'driver', 'vehicle', 'estimate']):
        return 'ride_hailing'
    elif any(k in data for k in ['hotel', 'room', 'checkin', 'checkout']):
        return 'hotel'
    elif any(k in data for k in ['flight', 'airline', 'departure', 'arrival', 'flight_number']):
        return 'flight'
    elif any(k in data for k in ['train', 'train_number', 'departure_station', 'arrival_station']):
        return 'train'
    elif any(k in data for k in ['restaurant', 'cuisine', 'rating']):
        return 'restaurant'
    elif any(k in data for k in ['movie', 'cinema', 'showtime']):
        return 'movie'
    else:
        return 'custom'


def _infer_card_title(data: Dict, tool_name: str = "") -> str:
    """根据数据内容推断卡片标题"""
    if 'city' in data:
        date_str = data.get('date', '')
        if date_str:
            return f"{data['city']}天气 - {date_str}"
        return f"{data['city']}天气"
    elif 'name' in data:
        return data['name']
    elif 'title' in data:
        return data['title']
    elif 'location' in data:
        return f"位置: {data['location']}"
    elif tool_name:
        # 根据工具名称推断
        if 'weather' in tool_name.lower():
            return "天气信息"
        elif 'navigation' in tool_name.lower() or 'route' in tool_name.lower():
            return "导航路线"
        elif 'ride' in tool_name.lower() or 'taxi' in tool_name.lower():
            return "打车信息"
    return "查询结果"


def _infer_card_subtitle(data: Dict) -> Optional[str]:
    """推断卡片副标题"""
    if 'date' in data and 'city' in data:
        return data.get('date', '')
    elif 'address' in data:
        return data.get('address', '')
    elif 'location' in data:
        return data.get('location', '')
    return None


def _infer_card_icon(card_type: str) -> Optional[str]:
    """根据卡片类型推断图标"""
    icon_map = {
        'weather': '🌤️',
        'navigation': '🧭',
        'ride_hailing': '🚕',
        'hotel': '🏨',
        'flight': '✈️',
        'train': '🚄',
        'restaurant': '🍽️',
        'movie': '🎬',
        'custom': '📋'
    }
    return icon_map.get(card_type)


def _infer_card_expires_at(data: Dict, card_type: str) -> Optional[str]:
    """推断卡片过期时间"""
    from datetime import datetime, timedelta
    
    if card_type == 'weather':
        # 天气卡片通常当天有效
        if 'date' in data:
            try:
                date_obj = datetime.fromisoformat(data['date'].replace('Z', '+00:00'))
                # 设置为当天23:59:59
                expires_at = date_obj.replace(hour=23, minute=59, second=59)
                return expires_at.isoformat()
            except:
                pass
        # 默认24小时后过期
        expires_at = datetime.now() + timedelta(hours=24)
        return expires_at.isoformat()
    elif card_type in ['navigation', 'ride_hailing']:
        # 导航和打车信息通常1小时后过期
        expires_at = datetime.now() + timedelta(hours=1)
        return expires_at.isoformat()

    return None


# ---------------------------------------------------------------------------
# 异步任务结果卡片构建（OpenClaw 执行完成后使用）
# ---------------------------------------------------------------------------

def build_async_task_result_card(
    user_id: int,
    task_id: str,
    task_description: str,
    result_markdown: str,
    task_type: str = "one_time",
    fallback_reason: Optional[str] = None,
    next_run_at: Optional[str] = None,
    executed_at: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[RichCard]:
    """
    构建 OpenClaw 任务执行结果卡片。

    Args:
        user_id: 用户 ID（calendar_user_id）
        task_id: 我们系统的任务 ID
        task_description: 任务描述
        result_markdown: 执行结果（Markdown 格式）
        task_type: periodic | research | one_time
        fallback_reason: 触发 OpenClaw 的原因
        next_run_at: 下次执行时间（仅周期任务）
        executed_at: 本次执行时间
        session_id: 关联会话 ID

    Returns:
        RichCard 对象，若构建失败则返回 None
    """
    try:
        manager = get_rich_card_manager()
        now = datetime.now().isoformat()
        exec_time = executed_at or now

        # 标题根据任务类型区分
        type_labels = {
            "periodic": "定期任务报告",
            "research": "调研报告",
            "one_time": "任务完成",
        }
        title = type_labels.get(task_type, "任务完成")

        # 副标题：任务描述截断
        subtitle = task_description if len(task_description) <= 30 else task_description[:28] + "…"

        # 操作按钮
        actions = []
        if task_type == "periodic" and next_run_at:
            actions.append({
                "label": f"下次执行: {_format_time_friendly(next_run_at)}",
                "action": "info",
            })
        actions.append({"label": "取消任务", "action": "cancel_task", "task_id": task_id})

        card_data = {
            "task_id": task_id,
            "task_description": task_description,
            "task_type": task_type,
            "fallback_reason": fallback_reason,
            "result_markdown": result_markdown,
            "executed_at": exec_time,
            "next_run_at": next_run_at,
            "session_id": session_id,
            "actions": actions,
        }

        card = manager.create_card(
            event_id=0,
            user_id=user_id,
            card_type="async_task_result",
            title=title,
            subtitle=subtitle,
            icon="🤖",
            data=card_data,
            source="openclaw",
        )
        logger.info(f"[RichCardManager] 异步任务结果卡片已创建: card_id={card.card_id}, task_id={task_id}")
        return card
    except Exception as e:
        logger.error(f"[RichCardManager] 构建异步任务结果卡片失败: {e}")
        return None


def _format_time_friendly(iso_str: str) -> str:
    """将 ISO 时间字符串转为友好显示格式。"""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%m/%d %H:%M")
    except Exception:
        return iso_str

