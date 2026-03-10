# -*- coding: utf-8 -*-
"""天气技能：高德天气。"""

import json
from typing import Any, List, Optional

from .base import Skill


class WeatherSkill(Skill):
    """天气能力：高德天气。"""

    @property
    def skill_id(self) -> str:
        return "weather"

    @property
    def display_name(self) -> str:
        return "天气"

    def matches_tool(self, tool_name: str) -> bool:
        if not tool_name:
            return False
        return "maps_weather" in tool_name or "amap_maps-maps_weather" == tool_name.strip()

    def get_business_short(self, tool_name: str) -> Optional[str]:
        return "查询天气"

    def get_thinking_after_result(self, tool_name: str, tool_result: Any = None) -> Optional[str]:
        if tool_result is not None:
            try:
                res = tool_result if isinstance(tool_result, dict) else json.loads(str(tool_result))
                if isinstance(res, dict):
                    city = res.get("city") or res.get("province") or ""
                    weather = res.get("weather") or ""
                    temp = res.get("temperature") or ""
                    if city and weather:
                        return f"已查询到{city}的天气：{weather}，温度{temp}℃。正在整理信息准备回复。"
                    forecasts = res.get("forecasts") or res.get("lives")
                    if isinstance(forecasts, list) and forecasts:
                        first = forecasts[0] if isinstance(forecasts[0], dict) else {}
                        city = first.get("city") or first.get("province") or city
                        if city:
                            return f"已查询到{city}的天气预报信息。正在整理后为您回复。"
            except Exception:
                pass
        return "已查询到天气信息，正在整理后回复。"

    def tool_categories(self) -> List[str]:
        return ["amap"]
