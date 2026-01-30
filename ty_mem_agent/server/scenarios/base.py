# -*- coding: utf-8 -*-
"""
场景基类：定义阶段、跳转条件、TTS 时机等接口。
各业务场景（打车、股票、会议）实现此接口，便于配置与扩展。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ScenarioToolResult:
    """场景对某次 tool_result 的处理结果，供 WebSocket 层发送卡片/TTS、更新状态。"""
    # 本次是否应播报一句 TTS（如 get_user_profile 后的「已查到/请提供电话」）
    tts_to_say: Optional[str] = None
    # 是否在「推送车型卡片」之前抑制模型输出的 TTS（避免「北门位置…」等中间句播报）
    suppress_tts_until_cards: bool = False
    # 推送车型确认卡片后应播报的一句 TTS（起点、终点、请确认并选择车型）
    tts_after_ride_confirm_cards: Optional[str] = None
    # 供后续使用的起点/终点（用于拼 tts_after_ride_confirm_cards）
    origin: Optional[str] = None
    destination: Optional[str] = None
    # 其他扩展（如 state 更新）
    extra: Dict[str, Any] = field(default_factory=dict)


class ScenarioHandler(ABC):
    """场景处理器抽象基类。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """场景名称，如 ride_hailing。"""
        pass

    @abstractmethod
    def applies_to(self, user_message: str) -> bool:
        """根据用户首条消息判断是否进入本场景。"""
        pass

    def on_tool_result(
        self,
        tool_name: str,
        tool_result: Any,
        tool_args: Any,
        context: Dict[str, Any],
    ) -> Optional[ScenarioToolResult]:
        """
        处理某次 tool_result，返回本场景的决策（TTS、是否抑制模型 TTS、推送卡片后 TTS 等）。
        不负责具体发卡/发 TTS，只返回「要说什么、是否抑制」等。
        """
        return None

    def should_tts_model_output(self, context: Dict[str, Any]) -> bool:
        """
        当前是否应对「模型输出的一句话」做 TTS。
        例如叫车场景在「已查到电话」之后、推送车型卡片之前应返回 False。
        """
        return True
