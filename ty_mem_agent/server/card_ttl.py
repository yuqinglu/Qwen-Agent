# -*- coding: utf-8 -*-
"""卡片 TTL：加载配置，计算卡片岛 expireAt（Unix 秒）与历史展示是否过期。"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from loguru import logger

from ty_mem_agent.config.settings import settings

_config_cache: Optional[Dict[str, Any]] = None


def _default_config_path() -> Path:
    env_path = getattr(settings, "CARD_TTL_CONFIG_PATH", None) or ""
    if env_path.strip():
        return Path(env_path).expanduser()
    return Path(__file__).resolve().parent.parent / "config" / "card_display_ttl.yaml"


def load_card_ttl_config(force_reload: bool = False) -> Dict[str, Any]:
    global _config_cache
    if _config_cache is not None and not force_reload:
        return _config_cache
    path = _default_config_path()
    if not path.is_file():
        logger.warning(f"卡片 TTL 配置文件不存在，使用内置默认: {path}")
        _config_cache = {
            "island_ttl_seconds": {"default": 86400, "by_card_type": {}},
            "message_ttl_seconds": {"default": 86400, "by_card_type": {}},
            "ride_hailing_stage_ttl_seconds": {},
        }
        return _config_cache
    with open(path, "r", encoding="utf-8") as f:
        _config_cache = yaml.safe_load(f) or {}
    return _config_cache


def reset_card_ttl_config_cache() -> None:
    """供单元测试重置缓存。"""
    global _config_cache
    _config_cache = None


def _resolve_ttl_from_section(
    section: Dict[str, Any],
    card_type: str,
    ride_stage: Optional[str],
) -> Optional[int]:
    """
    返回 TTL 秒数；None 表示永不过期。
    优先级：ride_hailing 的 stage -> by_card_type[type] -> default
    """
    if not section:
        return 86400
    stages = section.get("ride_hailing_stage_ttl_seconds") or {}
    if card_type == "ride_hailing" and ride_stage and ride_stage in stages:
        v = stages.get(ride_stage)
        return v if isinstance(v, int) else None
    by_type = section.get("by_card_type") or {}
    if card_type in by_type:
        v = by_type[card_type]
        if v is None:
            return None
        if isinstance(v, int):
            return v
    d = section.get("default")
    if d is None:
        return None
    if isinstance(d, int):
        return d
    return 86400


def _ride_stage(card: Dict[str, Any]) -> Optional[str]:
    data = card.get("data")
    if not isinstance(data, dict):
        return None
    s = data.get("stage")
    return str(s) if s is not None and s != "" else None


def _section_with_ride_stages(cfg: Dict[str, Any], section_key: str) -> Dict[str, Any]:
    """将根级 ride_hailing_stage_ttl_seconds 并入 island/message 段落（与 YAML 结构一致）。"""
    section: Dict[str, Any] = dict(cfg.get(section_key) or {})
    root_stages = cfg.get("ride_hailing_stage_ttl_seconds")
    if root_stages and isinstance(root_stages, dict):
        section.setdefault("ride_hailing_stage_ttl_seconds", root_stages)
    return section


def get_island_ttl_seconds(card: Dict[str, Any]) -> Optional[int]:
    cfg = load_card_ttl_config()
    section = _section_with_ride_stages(cfg, "island_ttl_seconds")
    ct = (card.get("card_type") or "unknown").strip() or "unknown"
    return _resolve_ttl_from_section(section, ct, _ride_stage(card))


def get_message_ttl_seconds(card: Dict[str, Any]) -> Optional[int]:
    cfg = load_card_ttl_config()
    section = _section_with_ride_stages(cfg, "message_ttl_seconds")
    ct = (card.get("card_type") or "unknown").strip() or "unknown"
    return _resolve_ttl_from_section(section, ct, _ride_stage(card))


def resolve_island_expire_at_unix(card: Dict[str, Any]) -> Optional[int]:
    """
    卡片岛可选字段 expireAt：Unix 秒级过期时刻；永不过期返回 None（不传该键）。

    优先级：
    1. 卡片已有 expires_at（领域逻辑或之前 ensure_card_expires_at_field 设置）→ 直接转 Unix 秒
    2. 无 expires_at 时按 TTL 配置计算 now + island_ttl
    3. TTL 配置为 None（永不过期）→ 返回 None
    """
    existing = _parse_iso_to_utc(card.get("expires_at"))
    if existing is not None:
        return int(existing.timestamp())
    ttl = get_island_ttl_seconds(card)
    if ttl is None:
        return None
    return int(time.time()) + int(ttl)


def ensure_card_expires_at_field(card: Dict[str, Any]) -> None:
    """
    在 card['expires_at'] 为空时，按 message TTL 写入朴素本地时间字符串（与 created_at 格式一致）；
    已有值（领域逻辑设置）则不覆盖，保持一致性。
    若 TTL 配置为 None（永不过期）则写入 None。
    """
    if card.get("expires_at") is not None:
        return
    ttl = get_message_ttl_seconds(card)
    if ttl is None:
        card["expires_at"] = None
        return
    exp = datetime.now() + timedelta(seconds=int(ttl))
    card["expires_at"] = exp.replace(microsecond=0).isoformat()


def _parse_iso_to_utc(s: Optional[str]) -> Optional[datetime]:
    """
    解析 ISO8601 字符串为 UTC datetime。
    - 带时区信息（含 Z 或 +HH:MM）直接转 UTC。
    - 无时区信息的朴素时间视为**服务器本地时间**（astimezone 自动附加本地时区再转 UTC），
      避免错误地把本地时间当成 UTC 造成 8 小时偏差。
    """
    if not s or not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    try:
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.astimezone(timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _card_created_utc(card: Dict[str, Any]) -> Optional[datetime]:
    return _parse_iso_to_utc(card.get("created_at"))


def card_is_expired_for_display(card: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """
    用于历史消息投影：是否不再展示该卡片。
    配置为永不过期（message TTL 为 None）则永不过期。
    """
    now = now or datetime.now(timezone.utc)
    ttl = get_message_ttl_seconds(card)
    if ttl is None:
        return False

    exp = _parse_iso_to_utc(card.get("expires_at"))
    if exp is not None:
        return now > exp

    created = _card_created_utc(card)
    if created is None:
        return False
    return now > created + timedelta(seconds=int(ttl))
