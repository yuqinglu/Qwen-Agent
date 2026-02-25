# -*- coding: utf-8 -*-
"""打车技能：滴滴 + 高德地点 + 用户画像（手机号）。"""

import json
from typing import Any, List, Optional

from .base import Skill


# 工具名或包含关系 -> (面向用户的短描述, 工具完成后的思考句)
_RIDE_HAILING_MAP = {
    "get_user_profile": (
        "查询您的手机号",
        "已查到您的手机号。接下来需要确认您的上车地点和目的地，以便为您叫车。",
    ),
    "amap_maps-maps_text_search": (
        "查询地点信息",
        "已确认相关地点信息。接下来将查询可选的车型与预估价格。",
    ),
    "amap_maps-maps_geo": (
        "查询地点坐标",
        "已确认地点坐标。接下来将用于查询车型与价格。",
    ),
    "Didi-Ride-maps_textsearch": (
        "确认打车起点与终点",
        "已确认打车起点与终点。正在查询车型与预估价格。",
    ),
    "Didi-Ride-taxi_estimate": (
        "查询车型与预估价格",
        "已获取车型与预估价格。请确认起终点无误后选择一种车型，即可为您下单。",
    ),
    "Didi-Ride-taxi_create_order": (
        "提交打车订单",
        "已提交订单，正在为您叫车。",
    ),
    "Didi-Ride-taxi_cancel_order": (
        "取消订单",
        "已为您取消订单。",
    ),
    "Didi-Ride-taxi_query_order": (
        "查询订单状态",
        "已查询到订单状态。",
    ),
}


class RideHailingSkill(Skill):
    """打车能力：滴滴、高德地点、用户手机号。"""

    @property
    def skill_id(self) -> str:
        return "ride_hailing"

    @property
    def display_name(self) -> str:
        return "打车"

    def matches_tool(self, tool_name: str) -> bool:
        if not tool_name:
            return False
        name = tool_name.strip()
        if name == "get_user_profile":
            return True
        if "Didi-Ride-" in name or (("Didi" in name or "taxi" in name) and "Ride" in name):
            return True
        if "amap_maps-maps_text_search" in name or "amap_maps-maps_geo" in name:
            return True
        if "amap" in name.lower() and ("maps_text_search" in name or "maps_geo" in name):
            return True
        return False

    def get_business_short(self, tool_name: str) -> Optional[str]:
        for key, (short, _) in _RIDE_HAILING_MAP.items():
            if key in tool_name or tool_name == key:
                return short
        if "amap" in tool_name.lower() or "maps_" in tool_name:
            return "查询地点或地图信息"
        if "Didi" in tool_name or "taxi" in tool_name:
            return "处理打车相关请求"
        return None

    def get_thinking_after_result(self, tool_name: str, tool_result: Any = None) -> Optional[str]:
        name = tool_name.strip()
        res = None
        if tool_result is not None:
            try:
                res = tool_result if isinstance(tool_result, dict) else json.loads(str(tool_result))
            except Exception:
                res = None

        if name == "get_user_profile":
            if isinstance(res, dict):
                if not res.get("success"):
                    return "未查到您的手机号，需要您提供电话号码以便为您叫车。"
                profile = res.get("profile") if isinstance(res.get("profile"), dict) else None
                has_phone = bool(profile and profile.get("phone") and str(profile.get("phone")).strip())
                if not has_phone:
                    return "未查到您的手机号，需要您提供电话号码以便为您叫车。"
            return _RIDE_HAILING_MAP["get_user_profile"][1]

        if "maps_text_search" in name or "maps_geo" in name:
            if isinstance(res, dict):
                pois = res.get("pois") or res.get("geocodes")
                if isinstance(pois, list) and pois:
                    first = pois[0] if isinstance(pois[0], dict) else {}
                    place_name = first.get("name") or first.get("formatted_address") or ""
                    if place_name:
                        return f"已定位到「{place_name}」。接下来将查询可选的车型与预估价格。"
            return "已确认相关地点信息。接下来将查询可选的车型与预估价格。"

        if "taxi_estimate" in name:
            if isinstance(res, dict):
                prices = res.get("prices") or res.get("price_list")
                count = len(prices) if isinstance(prices, list) else 0
                if count > 0:
                    return f"已获取到{count}种车型及预估价格。请确认起终点无误后选择车型下单。"
            return _RIDE_HAILING_MAP.get("Didi-Ride-taxi_estimate", ("", "已获取车型与预估价格。"))[1]

        for key, (_, thinking) in _RIDE_HAILING_MAP.items():
            if key in name or name == key:
                return thinking

        if "amap" in name.lower():
            return "已查询到地点信息。"
        if "Didi" in name or "taxi" in name:
            return "已处理打车相关请求。"
        return None

    def tool_categories(self) -> List[str]:
        return ["profile", "amap", "didi"]
