# -*- coding: utf-8 -*-
"""
技能层基类与注册表

每个 Skill 同时覆盖两层能力，开发者只需一个文件即可完整实现一个业务领域：
  1. 工具匹配层：工具名 → 用户可见文案，供「深度思考」步骤展示使用
  2. 交互流程层：多轮交互中的 TTS 时机与卡片推送控制，默认为无状态（直接返回 None/True）

参考 OpenClaw Skills 设计：技能可被注册、发现、组合，后续可扩展为用户自选开关。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger


# ---------------------------------------------------------------------------
# 交互流程层：工具结果的 TTS/卡片决策
# ---------------------------------------------------------------------------

@dataclass
class SkillInteractionResult:
    """
    某次工具调用完成后，技能对 TTS / 卡片推送的决策结果。
    WebSocket 层据此发送 TTS 语音、抑制模型中间输出等。

    字段说明：
      tts_to_say                  — 立即播报这句 TTS（如查到电话后播报「已查到/请提供电话」）
      suppress_tts_until_cards    — 在推送卡片前抑制模型流式输出的 TTS（避免中间句干扰）
      tts_after_card              — 推送确认卡片后播报的一句 TTS（如打车起终点确认句）
      origin / destination        — 扩展字段，供打车等场景传递起终点信息
      extra                       — 其他自定义扩展数据
    """
    tts_to_say: Optional[str] = None
    suppress_tts_until_cards: bool = False
    tts_after_card: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 技能基类
# ---------------------------------------------------------------------------

class Skill(ABC):
    """
    单个业务技能基类，同时覆盖工具文案映射与交互流程控制。

    最小实现：只需重写 skill_id、matches_tool、get_business_short。
    交互流程控制（TTS 时机）按需重写 applies_to、on_tool_result、should_tts_model_output。
    """

    # ------------------------------------------------------------------
    # 元数据
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def skill_id(self) -> str:
        """技能唯一标识，如 ride_hailing、weather、todo。"""

    @property
    def display_name(self) -> str:
        """展示名称，可选，默认使用 skill_id。"""
        return self.skill_id

    @property
    def description(self) -> str:
        """技能说明，可选，用于 README / 管理界面展示。"""
        return ""

    # ------------------------------------------------------------------
    # 工具匹配层（原 skills 功能）
    # ------------------------------------------------------------------

    def matches_tool(self, tool_name: str) -> bool:
        """当前技能是否处理该工具（用于解析 business_short / thinking_after）。"""
        return False

    def get_business_short(self, tool_name: str) -> Optional[str]:
        """面向用户的短描述（用于深度思考步骤文案），不暴露工具名。未处理则返回 None。"""
        return None

    def get_thinking_after_result(self, tool_name: str, tool_result: Any = None) -> Optional[str]:
        """工具调用完成后推送给用户的思考句（业务化、无工具名）。未处理则返回 None。"""
        return None

    def tool_categories(self) -> List[str]:
        """
        本技能依赖的 ToolRegistry 类别，如 ["didi", "amap", "profile"]。
        用于后续「按技能只注入部分工具」以节省 Agent 上下文 token。
        """
        return []

    # ------------------------------------------------------------------
    # 交互流程层（原 scenarios 功能，按需重写）
    # ------------------------------------------------------------------

    def applies_to(self, user_message: str) -> bool:
        """
        根据用户首条消息判断是否进入本技能的交互流程（如打车场景）。
        无状态技能（天气、待办等）保持默认值 False 即可，无需重写。
        """
        return False

    def applies_to_with_history(self, history_messages: List[str], current_message: str) -> bool:
        """
        扩展版意图识别：结合最近几轮用户消息 + 当前消息判断是否进入场景。

        默认实现只是调用 applies_to(current_message)，保持向后兼容；
        需要多轮语境感知的技能（如打车）可以重写本方法。
        """
        return self.applies_to(current_message)

    def on_tool_result(
        self,
        tool_name: str,
        tool_result: Any,
        tool_args: Any,
        context: Dict[str, Any],
    ) -> Optional[SkillInteractionResult]:
        """
        处理某次工具调用完成事件，返回 TTS/卡片推送决策。
        不负责具体发卡/发 TTS，只返回「要说什么、是否抑制」等决策。
        无交互流程需求的技能保持默认 None 即可，无需重写。
        """
        return None

    def should_tts_model_output(self, context: Dict[str, Any]) -> bool:
        """
        当前是否应对「模型输出的一句话」做 TTS。
        例如叫车场景在「已查到电话」之后、推送车型卡片之前应返回 False。
        无状态技能保持默认值 True 即可，无需重写。
        """
        return True


# ---------------------------------------------------------------------------
# 默认兜底文案
# ---------------------------------------------------------------------------

_DEFAULT_BUSINESS_SHORT = "获取所需信息"
_DEFAULT_THINKING_AFTER = "已获取相关信息。接下来将根据结果继续为您处理。"


# ---------------------------------------------------------------------------
# 技能注册表
# ---------------------------------------------------------------------------

class SkillRegistry:
    """
    技能注册表：统一管理所有已注册技能，按注册顺序优先级匹配。

    职责：
      - 工具名 → 业务文案（供深度思考步骤展示）
      - 用户消息 → 交互流程技能
    """

    _instance: Optional["SkillRegistry"] = None

    def __new__(cls) -> "SkillRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if not hasattr(self, "_skills") or self._skills is None:
            self._skills: List[Skill] = []

    def register(self, skill: Skill) -> "SkillRegistry":
        """注册技能，注册顺序即匹配优先级（更具体的技能应先注册）。"""
        if skill not in self._skills:
            self._skills.append(skill)
            logger.debug(f"技能已注册: {skill.skill_id}")
        return self

    # ------------------------------------------------------------------
    # 工具匹配层接口
    # ------------------------------------------------------------------

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
        """将工具名转为面向用户的短描述，不暴露工具名。"""
        if not tool_name or not str(tool_name).strip():
            return _DEFAULT_BUSINESS_SHORT
        skill = self.get_skill_for_tool(str(tool_name).strip())
        if skill:
            desc = skill.get_business_short(str(tool_name).strip())
            if desc:
                return desc
        return _DEFAULT_BUSINESS_SHORT

    def get_thinking_after_result(self, tool_name: Optional[str], tool_result: Any = None) -> str:
        """工具调用完成后，返回面向用户的思考句。"""
        if not tool_name or not str(tool_name).strip():
            return _DEFAULT_THINKING_AFTER
        skill = self.get_skill_for_tool(str(tool_name).strip())
        if skill:
            text = skill.get_thinking_after_result(str(tool_name).strip(), tool_result)
            if text:
                return text
        return _DEFAULT_THINKING_AFTER

    # ------------------------------------------------------------------
    # 交互流程层接口（替代原 scenarios.get_scenario_for_message）
    # ------------------------------------------------------------------

    def get_scenario_skill(self, user_message: str, history: Optional[List[str]] = None) -> Optional[Skill]:
        """
        根据用户首条消息判断是否进入某技能的交互流程。
        若匹配则返回该技能，否则返回 None。
        """
        if not user_message or not user_message.strip():
            return None
        msg = user_message.strip()

        # 若提供了历史消息，则优先使用多轮语境感知的接口
        if history is not None:
            for s in self._skills:
                try:
                    if s.applies_to_with_history(history, msg):
                        return s
                except TypeError:
                    # 兼容旧实现（某些技能可能尚未定义该方法）
                    if s.applies_to(msg):
                        return s
            return None

        # 否则退回到仅基于当前消息的判定
        for s in self._skills:
            if s.applies_to(msg):
                return s
        return None

    # ------------------------------------------------------------------
    # 工具类别接口
    # ------------------------------------------------------------------

    def get_tool_categories_for_skills(self, skill_ids: List[str]) -> List[str]:
        """返回给定技能集合所依赖的 ToolRegistry 类别并去重。"""
        seen: set = set()
        result: List[str] = []
        id_set = set(skill_ids)
        for s in self._skills:
            if s.skill_id in id_set:
                for cat in s.tool_categories():
                    if cat not in seen:
                        seen.add(cat)
                        result.append(cat)
        return result

    def all_skills(self) -> List[Skill]:
        """返回已注册技能列表（只读副本）。"""
        return list(self._skills)


# ---------------------------------------------------------------------------
# 单例访问函数
# ---------------------------------------------------------------------------

_skill_registry: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    """获取技能注册表单例。"""
    global _skill_registry
    if _skill_registry is None:
        _skill_registry = SkillRegistry()
    return _skill_registry
