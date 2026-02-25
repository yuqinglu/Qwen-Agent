# -*- coding: utf-8 -*-
"""
技能层基类与注册表
将「工具名 → 面向用户的业务描述」从 WebSocket 服务中抽离，便于按能力扩展（类似 Clawbot 技能配置）。
后续可扩展：按技能过滤注入 Agent 的工具，控制上下文 token。
"""

from abc import ABC, abstractmethod
from typing import Any, List, Optional

from loguru import logger


class Skill(ABC):
    """
    单个能力/技能：负责声明自己处理哪些工具，以及这些工具对用户展示的文案（不暴露工具名）。
    与 scenarios 解耦：scenarios 管 TTS/卡片时机，skills 管「深度思考」里的业务化描述。
    """

    @property
    @abstractmethod
    def skill_id(self) -> str:
        """技能唯一标识，如 ride_hailing、weather、todo。"""
        pass

    @property
    def display_name(self) -> str:
        """展示名，可选。"""
        return self.skill_id

    def matches_tool(self, tool_name: str) -> bool:
        """当前技能是否处理该工具（用于解析 business_short / thinking_after）。"""
        return False

    def get_business_short(self, tool_name: str) -> Optional[str]:
        """面向用户的短描述（用于 plan_update 步骤文案），不暴露工具名。未处理则返回 None。"""
        return None

    def get_thinking_after_result(self, tool_name: str, tool_result: Any = None) -> Optional[str]:
        """工具调用完成后推送给用户的思考句（业务化、无工具名）。可结合 tool_result 区分成功/失败。未处理则返回 None。"""
        return None

    def tool_categories(self) -> List[str]:
        """
        本技能依赖的 ToolRegistry 类别，如 ["didi", "amap", "profile"]。
        用于后续「按技能只注入部分工具」以节省 Agent 上下文 token。
        """
        return []


# 默认兜底文案
_DEFAULT_BUSINESS_SHORT = "获取所需信息"
_DEFAULT_THINKING_AFTER = "已获取相关信息。接下来将根据结果继续为您处理。"


class SkillRegistry:
    """技能注册表：按注册顺序匹配工具，先匹配先生效。"""

    _instance: Optional["SkillRegistry"] = None

    def __new__(cls) -> "SkillRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if not hasattr(self, "_skills") or self._skills is None:
            self._skills: List[Skill] = []

    def register(self, skill: Skill) -> "SkillRegistry":
        """注册一个技能，顺序即匹配优先级（更具体的技能应先注册）。"""
        if skill not in self._skills:
            self._skills.append(skill)
            logger.debug(f"技能已注册: {skill.skill_id}")
        return self

    def get_skill_for_tool(self, tool_name: str) -> Optional[Skill]:
        """返回第一个声明处理该工具的技能。"""
        if not tool_name or not str(tool_name).strip():
            return None
        name = str(tool_name).strip()
        for s in self._skills:
            if s.matches_tool(name):
                return s
        return None

    def get_business_short(self, tool_name: Optional[str]) -> str:
        """将工具名转为面向用户的短描述（用于 plan_update），不暴露工具名。"""
        if not tool_name or not str(tool_name).strip():
            return _DEFAULT_BUSINESS_SHORT
        skill = self.get_skill_for_tool(str(tool_name).strip())
        if skill:
            desc = skill.get_business_short(str(tool_name).strip())
            if desc:
                return desc
        return _DEFAULT_BUSINESS_SHORT

    def get_thinking_after_result(self, tool_name: Optional[str], tool_result: Any = None) -> str:
        """工具调用完成后，返回面向用户的思考句（业务化、无工具名）。可传 tool_result 供技能区分成功/失败。"""
        if not tool_name or not str(tool_name).strip():
            return _DEFAULT_THINKING_AFTER
        skill = self.get_skill_for_tool(str(tool_name).strip())
        if skill:
            text = skill.get_thinking_after_result(str(tool_name).strip(), tool_result)
            if text:
                return text
        return _DEFAULT_THINKING_AFTER

    def all_skills(self) -> List[Skill]:
        """返回已注册技能列表（只读）。"""
        return list(self._skills)

    def get_tool_categories_for_skills(self, skill_ids: List[str]) -> List[str]:
        """返回给定技能集合所依赖的 ToolRegistry 类别并去重（用于后续按技能过滤工具、节省 token）。"""
        seen = set()
        result: List[str] = []
        id_set = set(skill_ids)
        for s in self._skills:
            if s.skill_id in id_set:
                for cat in s.tool_categories():
                    if cat not in seen:
                        seen.add(cat)
                        result.append(cat)
        return result


_skill_registry: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    """获取技能注册表单例。"""
    global _skill_registry
    if _skill_registry is None:
        _skill_registry = SkillRegistry()
    return _skill_registry
