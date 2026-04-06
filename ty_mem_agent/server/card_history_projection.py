# -*- coding: utf-8 -*-
"""会话历史 rich_cards 投影：打车按 order_id 合并阶段、按 TTL 剔除过期卡片。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ty_mem_agent.server.card_ttl import card_is_expired_for_display

# cancelled 优先于一切其它阶段（用户最终取消用车）
RIDE_STAGE_RANK: Dict[str, int] = {
    "cancelled": 100,
    "driver_arrived": 90,
    "driver_approaching": 80,
    "driver_assigned": 70,
    "success": 60,
    "executing": 50,
    "confirm": 40,
}


def _ride_order_id(card: Dict[str, Any]) -> str:
    data = card.get("data") or {}
    if not isinstance(data, dict):
        return ""
    oid = data.get("order_id")
    return str(oid).strip() if oid is not None and str(oid).strip() else ""


def _ride_stage(card: Dict[str, Any]) -> str:
    data = card.get("data") or {}
    if not isinstance(data, dict):
        return ""
    s = data.get("stage")
    return str(s) if s is not None else ""


def _winning_card_id_per_order(messages: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    每个 order_id 保留一张卡片：阶段 rank 最高；同 rank 取消息/卡片顺序靠后的（更新信息）。
    返回 order_id -> card_id
    """
    candidates: Dict[str, List[Tuple[int, int, int, str]]] = defaultdict(list)
    for mi, msg in enumerate(messages):
        for ci, c in enumerate(msg.get("rich_cards") or []):
            if not isinstance(c, dict):
                continue
            if c.get("card_type") != "ride_hailing":
                continue
            oid = _ride_order_id(c)
            if not oid:
                continue
            rank = RIDE_STAGE_RANK.get(_ride_stage(c), 0)
            cid = str(c.get("card_id") or "")
            candidates[oid].append((rank, mi, ci, cid))
    winners: Dict[str, str] = {}
    for oid, lst in candidates.items():
        if not lst:
            continue
        lst.sort()
        winners[oid] = lst[-1][3]
    return winners


def merge_ride_hailing_by_order_in_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """原地逻辑可改为拷贝；此处返回新列表，不修改入参。"""
    winners = _winning_card_id_per_order(messages)
    out: List[Dict[str, Any]] = []
    for msg in messages:
        m = dict(msg)
        new_cards: List[Any] = []
        for c in msg.get("rich_cards") or []:
            if not isinstance(c, dict):
                new_cards.append(c)
                continue
            if c.get("card_type") != "ride_hailing":
                new_cards.append(c)
                continue
            oid = _ride_order_id(c)
            if not oid:
                new_cards.append(c)
                continue
            cid = str(c.get("card_id") or "")
            if winners.get(oid) == cid:
                new_cards.append(c)
        m["rich_cards"] = new_cards
        out.append(m)
    return out


def filter_expired_rich_cards_in_messages(
    messages: List[Dict[str, Any]],
    now: datetime,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for msg in messages:
        m = dict(msg)
        cards = m.get("rich_cards") or []
        kept = [
            c
            for c in cards
            if not isinstance(c, dict) or not card_is_expired_for_display(c, now)
        ]
        m["rich_cards"] = kept
        out.append(m)
    return out


def project_messages_rich_cards_for_display(
    messages: List[Dict[str, Any]],
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    先按 order_id 合并打车卡片，再剔除过期卡片。
    messages 每项须含 rich_cards 列表。
    """
    now = now or datetime.now(timezone.utc)
    merged = merge_ride_hailing_by_order_in_messages(messages)
    return filter_expired_rich_cards_in_messages(merged, now)


def project_flat_rich_cards_for_display(
    cards: List[Dict[str, Any]],
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    会话级卡片列表（无消息维度）：先按 order_id 合并打车，再 TTL 过滤。
    """
    if not cards:
        return cards
    now = now or datetime.now(timezone.utc)
    wrapped = [{"rich_cards": list(cards)}]
    merged = merge_ride_hailing_by_order_in_messages(wrapped)[0]["rich_cards"]
    return [c for c in merged if isinstance(c, dict) and not card_is_expired_for_display(c, now)]
