# -*- coding: utf-8 -*-
"""
场景层：按业务场景（打车、股票、会议等）拆分状态阶段与交互逻辑。
每个场景定义自己的阶段、跳转条件、TTS 时机，避免 general_chat_websocket_service 臃肿。
"""

from .base import ScenarioHandler, ScenarioToolResult
from .ride_hailing import RideHailingScenario

# 注册所有场景，按优先级匹配（先匹配先生效）
_SCENARIOS = [
    RideHailingScenario(),
]


def get_scenario_for_message(user_message: str):
    """根据用户首条消息判断是否进入某场景；若有则返回该场景处理器，否则返回 None。"""
    if not (user_message or user_message.strip()):
        return None
    msg = (user_message or "").strip()
    for s in _SCENARIOS:
        if s.applies_to(msg):
            return s
    return None


__all__ = [
    "ScenarioHandler",
    "ScenarioToolResult",
    "get_scenario_for_message",
    "RideHailingScenario",
]
