# -*- coding: utf-8 -*-
"""待办/日历技能：日历 MCP、待办提取。"""

from typing import Any, List, Optional

from .base import Skill


# 日历、待办相关工具 -> (短描述, 思考句)
_TODO_MAP = {
    "calendar-service-createOneTimeEvent": (
        "创建日程",
        "已为您创建日程。",
    ),
    "calendar-service-createRecurringEvent": (
        "创建重复日程",
        "已为您创建重复日程。",
    ),
    "calendar-service-updateEvent": (
        "更新日程",
        "已更新日程。",
    ),
    "calendar-service-deleteEvent": (
        "删除日程",
        "已删除日程。",
    ),
    "calendar-service-getEvents": (
        "查询日程",
        "已查询到日程信息。",
    ),
    "createOneTimeEvent": (
        "创建日程",
        "已为您创建日程。",
    ),
    "createRecurringEvent": (
        "创建重复日程",
        "已为您创建重复日程。",
    ),
    "updateEvent": (
        "更新日程",
        "已更新日程。",
    ),
    "deleteEvent": (
        "删除日程",
        "已删除日程。",
    ),
    "getEvents": (
        "查询日程",
        "已查询到日程信息。",
    ),
}


class TodoSkill(Skill):
    """待办/日历能力。"""

    @property
    def skill_id(self) -> str:
        return "todo"

    @property
    def display_name(self) -> str:
        return "待办/日历"

    def matches_tool(self, tool_name: str) -> bool:
        if not tool_name:
            return False
        name = tool_name.strip().lower()
        if "calendar" in name or "event" in name:
            return True
        if "todo" in name and "extract" in name:
            return True
        return False

    def get_business_short(self, tool_name: str) -> Optional[str]:
        for key, (short, _) in _TODO_MAP.items():
            if key in tool_name or tool_name == key:
                return short
        if "calendar" in tool_name.lower() or "event" in tool_name.lower():
            return "处理日程/待办"
        if "todo" in tool_name.lower():
            return "处理待办信息"
        return None

    def get_thinking_after_result(self, tool_name: str, tool_result: Any = None) -> Optional[str]:
        for key, (_, thinking) in _TODO_MAP.items():
            if key in tool_name or tool_name == key:
                return thinking
        if "calendar" in tool_name.lower() or "event" in tool_name.lower():
            return "已处理日程相关操作。"
        if "todo" in tool_name.lower():
            return "已处理待办相关信息。"
        return None

    def tool_categories(self) -> List[str]:
        return ["calendar", "todo_extractor"]
