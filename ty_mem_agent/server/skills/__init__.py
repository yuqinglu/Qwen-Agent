# -*- coding: utf-8 -*-
"""
技能层：可配置能力与工具→业务描述映射
- 将「工具名 → 用户可见文案」从 general_chat_websocket_service 抽离，便于扩展（类似 Clawbot 技能）。
- 后续可扩展：按技能只注入部分工具到 Agent，控制上下文 token。
"""

from .base import Skill, SkillRegistry, get_skill_registry
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


# 首次访问时懒加载注册
def get_skill_registry_lazy() -> SkillRegistry:
    """获取技能注册表并确保默认技能已注册。"""
    _register_default_skills()
    return get_skill_registry()


__all__ = [
    "Skill",
    "SkillRegistry",
    "get_skill_registry",
    "get_skill_registry_lazy",
    "WeatherSkill",
    "RideHailingSkill",
    "TodoSkill",
    "GeneralSkill",
]
