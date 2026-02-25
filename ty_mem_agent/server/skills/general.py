# -*- coding: utf-8 -*-
"""通用兜底技能：未命中其他技能时使用，避免暴露工具名。"""

from typing import Any, List, Optional

from .base import Skill


class GeneralSkill(Skill):
    """兜底能力：任意工具都返回通用文案。"""

    @property
    def skill_id(self) -> str:
        return "general"

    @property
    def display_name(self) -> str:
        return "通用"

    def matches_tool(self, tool_name: str) -> bool:
        return True

    def get_business_short(self, tool_name: str) -> Optional[str]:
        if "amap" in tool_name.lower():
            return "查询地点或地图信息"
        if "Didi" in tool_name or "taxi" in tool_name:
            return "处理打车相关请求"
        return "获取所需信息"

    def get_thinking_after_result(self, tool_name: str, tool_result: Any = None) -> Optional[str]:
        if "amap" in tool_name.lower():
            return "已查询到地点或地图相关信息。"
        if "Didi" in tool_name or "taxi" in tool_name:
            return "已处理打车相关请求。"
        return "已获取相关信息。接下来将根据结果继续为您处理。"

    def tool_categories(self) -> List[str]:
        return []
