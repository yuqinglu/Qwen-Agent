# -*- coding: utf-8 -*-
"""
技能层：可配置业务能力

每个 Skill 同时覆盖两层：
  1. 工具文案映射
  2. 交互流程控制

开发者只需在本目录新增一个 Skill 子类并注册，即可完整覆盖一个业务领域。
参考已有实现：weather.py（纯文案映射）、ride_hailing.py（含交互流程）。
"""

from typing import List, Optional

from .base import Skill, SkillInteractionResult, SkillRegistry, get_skill_registry
from .weather import WeatherSkill
from .ride_hailing import RideHailingSkill
from .todo import TodoSkill
from .general import GeneralSkill


def _register_default_skills() -> None:
    """注册默认技能，更具体的技能先注册（天气先于打车，避免 amap weather 被打车命中）。"""
    reg = get_skill_registry()
    if reg.all_skills():
        return
    reg.register(WeatherSkill())
    reg.register(RideHailingSkill())
    reg.register(TodoSkill())
    reg.register(GeneralSkill())


def get_skill_registry_lazy() -> SkillRegistry:
    """获取技能注册表并确保默认技能已注册。"""
    _register_default_skills()
    return get_skill_registry()


def get_scenario_skill(user_message: str, history_messages: Optional[List[str]] = None) -> Optional[Skill]:
    """
    根据「最近几轮用户消息 + 当前消息」判断是否进入某技能的交互流程。

    Args:
        user_message: 当前这一轮用户消息文本
        history_messages: 最近若干轮用户消息文本列表（旧到新），可选

    Returns:
        匹配的 Skill 实例，或 None（无场景匹配）。
    """
    return get_skill_registry_lazy().get_scenario_skill(user_message, history=history_messages)


__all__ = [
    "Skill",
    "SkillInteractionResult",
    "SkillRegistry",
    "get_skill_registry",
    "get_skill_registry_lazy",
    "get_scenario_skill",
    "WeatherSkill",
    "RideHailingSkill",
    "TodoSkill",
    "GeneralSkill",
]
