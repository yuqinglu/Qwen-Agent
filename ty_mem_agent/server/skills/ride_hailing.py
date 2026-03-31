# -*- coding: utf-8 -*-
"""
打车技能：滴滴 + 高德地点 + 用户画像（手机号）

同时覆盖：
  - 工具匹配层：工具名 → 深度思考步骤文案
  - 交互流程层：多轮叫车交互的 TTS 时机与抑制控制
    · 阶段1：get_user_profile 返回后 → 播报「已查到/请提供电话/请问上车地点」
    · 阶段2：taxi_estimate 返回、车型卡片推送后 → 播报起终点确认句
    · 阶段2.5：卡片推送之前抑制模型中间输出（避免「北门位置…」等干扰语音）
"""

import json
import re
from typing import Any, Dict, List, Optional

from loguru import logger

from .base import Skill, SkillInteractionResult


# ---------------------------------------------------------------------------
# Agent 注入：与主系统提示「仅目的地则不调用工具」一致，强制以 get_user_profile 为准核对手机号
# ---------------------------------------------------------------------------

PROFILE_TOOL_ENFORCEMENT_MESSAGE = """【打车场景补充规则（本回合有效）】
1) 若用户本条消息仅提供目的地、明显未提供上车地点或起点信息，不要调用任何工具（包括 get_user_profile），只回复询问上车地点即可。
2) 除上述情况外，在调用任何地图或滴滴相关工具（含 Didi-Ride-taxi_estimate、taxi_create_order 等）之前，必须先调用一次 get_user_profile。系统中是否已有手机号仅以该工具返回的 JSON 为准；不得因对话里出现过号码、或推测用户已有号码而跳过此工具。
3) 若 get_user_profile 返回 success 但 profile 中无有效 phone，必须先请用户提供号码并调用 update_user_profile 保存后，再继续叫车相关工具。"""


def resolve_ride_card_user_phone(
    chat_manager: Any,
    session_id: Optional[str],
    calendar_user_id: int,
    agent_user_id: str,
    cached_from_profile_tool: Optional[str],
) -> Optional[str]:
    """
    打车预估/订单卡片展示用电话：同轮 get_user_profile 工具结果 → 画像库（多 user_id 主键）
    → 本会话近期用户/助手消息中的 11 位手机号。
    chat_manager 须实现 get_session_messages(session_id, limit=...)。
    """
    if cached_from_profile_tool:
        s = str(cached_from_profile_tool).strip()
        if s:
            return s
    try:
        from ty_mem_agent.memory.user_memory import get_integrated_memory

        um = get_integrated_memory().user_manager
        seen = set()
        candidate_ids = [
            agent_user_id,
            f"user_cal_{calendar_user_id}",
            str(calendar_user_id),
        ]
        for cid in candidate_ids:
            if not cid or cid in seen:
                continue
            seen.add(str(cid))
            try:
                profile = um.get_user_profile(str(cid))
            except Exception:
                continue
            if not profile:
                continue
            ph = getattr(profile, "phone", None)
            if ph is not None:
                raw = str(ph).strip()
                if raw:
                    return raw
    except Exception as e:
        logger.debug(f"从画像解析打车电话失败: {e}")

    if session_id and chat_manager is not None:
        pat = re.compile(r"\b1[3-9]\d{9}\b")
        try:
            recent = chat_manager.get_session_messages(session_id, limit=50)
            for msg in reversed(recent or []):
                role = getattr(msg, "role", None)
                if role not in ("user", "assistant"):
                    continue
                content = (getattr(msg, "content", None) or "") or ""
                m = pat.search(content)
                if m:
                    return m.group(0)
        except Exception as e:
            logger.debug(f"从会话消息解析打车电话失败: {e}")
    return None


# ---------------------------------------------------------------------------
# 工具 → 文案映射表
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _user_only_said_destination(user_message: Optional[str]) -> bool:
    """
    判断用户是否只说了目的地、未说上车地点（起点）。
    用于在 get_user_profile 返回后决定播报「正在为您查询车」还是「请问您的上车地点是哪里？」。
    """
    if not user_message or not isinstance(user_message, str):
        return False
    msg = user_message.strip()
    origin_keywords = ("从", "起点", "上车", "出发", "出发地", "我在", "我在哪", "从哪", "从这儿", "从这里")
    if any(k in msg for k in origin_keywords):
        return False
    dest_keywords = ("去", "到", "目的地", "到哪", "去哪")
    return any(k in msg for k in dest_keywords)


# ---------------------------------------------------------------------------
# 打车技能
# ---------------------------------------------------------------------------

class RideHailingSkill(Skill):
    """
    打车技能：滴滴、高德地点、用户手机号。

    交互流程层：
      - 场景/意图由主力大模型结合对话判断（无关键字匹配）
      - on_tool_result 在 get_user_profile / taxi_estimate 后注入 TTS
      - should_tts_model_output 在卡片推送之前抑制模型中间输出
    """

    @property
    def skill_id(self) -> str:
        return "ride_hailing"

    @property
    def display_name(self) -> str:
        return "打车"

    @property
    def description(self) -> str:
        return "叫车、打车、滴滴相关功能，集成高德地图地点查询与滴滴打车下单。"

    # ------------------------------------------------------------------
    # 工具匹配层
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # 交互流程层（原 RideHailingScenario）
    # ------------------------------------------------------------------

    def applies_to(self, user_message: str) -> bool:
        """无历史时由主力模型判断当前句是否属于叫车场景（注册表异常回退等路径）。"""
        if not user_message or not user_message.strip():
            return False
        snippet = f"用户（当前轮）: {user_message.strip()[:800]}"
        return self._llm_is_ride_hailing_scenario(snippet)

    def applies_to_with_history(self, history_messages: List[str], current_message: str) -> bool:
        """
        仅有多轮用户文本、无助手侧上下文时，仍用主力模型判断（如未传 full_history 的调用）。
        """
        cur = (current_message or "").strip()
        if not cur:
            return False
        prior = list(history_messages or [])
        if prior and prior[-1].strip() == cur:
            prior = prior[:-1]
        lines: List[str] = []
        for h in prior[-16:]:
            lines.append(f"用户: {(h or '')[:500]}")
        block = "\n".join(lines) if lines else "(无更早的用户发言)"
        snippet = f"{block}\n\n用户（当前轮）: {cur[:800]}"
        return self._llm_is_ride_hailing_scenario(snippet)

    def on_tool_result(
        self,
        tool_name: str,
        tool_result: Any,
        tool_args: Any,
        context: Dict[str, Any],
    ) -> Optional[SkillInteractionResult]:
        """
        处理叫车关键工具的回调，决定 TTS 内容与抑制策略：
          - get_user_profile 返回后：注入「已查到/请提供电话/请问上车地点」
          - taxi_estimate 返回后：注入车型卡片推送后的确认 TTS
        """
        if not tool_name:
            return None

        if tool_name == "get_user_profile" and tool_result is not None:
            tts_to_say = None
            try:
                res = tool_result if isinstance(tool_result, dict) else json.loads(str(tool_result))
                if isinstance(res, dict):
                    if res.get("success"):
                        profile = res.get("profile") if isinstance(res.get("profile"), dict) else None
                        has_phone = False
                        if profile and profile.get("phone"):
                            ph = profile.get("phone")
                            if ph and str(ph).strip():
                                has_phone = True
                        user_msg = context.get("user_message") if isinstance(context, dict) else None
                        if has_phone and _user_only_said_destination(user_msg):
                            tts_to_say = "已查到您的电话号码。请问您的上车地点是哪里？"
                        else:
                            tts_to_say = (
                                "已查到您的电话号码，正在为您查询车型与价格。"
                                if has_phone
                                else "请提供您的电话号码，以便为您叫车。"
                            )
                    else:
                        tts_to_say = "请提供您的电话号码，以便为您叫车。"
            except Exception:
                pass
            if tts_to_say:
                return SkillInteractionResult(
                    tts_to_say=tts_to_say,
                    suppress_tts_until_cards=True,
                )
            return None

        if "Didi-Ride-taxi_estimate" in str(tool_name) and tool_args is not None:
            origin, destination = None, None
            try:
                args = tool_args if isinstance(tool_args, dict) else json.loads(str(tool_args))
                if isinstance(args, dict):
                    origin = args.get("from_name")
                    destination = args.get("to_name")
            except Exception:
                pass
            if origin and destination:
                tts_after = f"起点是{origin}，终点是{destination}，已为您查询到几种车型与预估价格，请确认起终点无误后选择一种车型。"
            else:
                tts_after = "已为您查询到几种车型与预估价格，请确认起终点无误后选择一种车型。"
            return SkillInteractionResult(
                tts_after_card=tts_after,
                origin=origin,
                destination=destination,
            )

        return None

    def should_tts_model_output(self, context: Dict[str, Any]) -> bool:
        """叫车场景：在「已查到/请提供电话」之后、推送车型卡片之前，不 TTS 模型输出。"""
        suppress = context.get("ride_hailing_suppress_tts_until_cards") is True
        pushed = context.get("ride_hailing_pushed_confirm_cards") is True
        if suppress and not pushed:
            return False
        return True

    def get_agent_message_prefixes(self) -> List[Dict[str, str]]:
        """注入本回合 system 规则，约束 get_user_profile 与滴滴/地图工具顺序。"""
        return [{"role": "system", "content": PROFILE_TOOL_ENFORCEMENT_MESSAGE}]

    # ------------------------------------------------------------------
    # 打车场景识别：主力大模型 + 对话上下文（无关键字规则）
    # ------------------------------------------------------------------

    def applies_to_with_full_history(
        self,
        full_history: List[Dict[str, str]],
        current_message: str,
    ) -> bool:
        """结合 user/assistant 完整轮次，由项目配置的主力模型判定是否处于叫车场景。"""
        if not current_message or not str(current_message).strip():
            return False
        recent = full_history[-20:] if len(full_history) > 20 else full_history
        lines: List[str] = []
        for m in recent:
            role = (m.get("role") or "user").strip().lower()
            label = "用户" if role == "user" else "助手"
            lines.append(f"{label}: {(m.get('content') or '')[:500]}")
        snippet = "\n".join(lines) if lines else f"用户（当前轮）: {str(current_message).strip()[:800]}"
        return self._llm_is_ride_hailing_scenario(snippet)

    def _parse_ride_hailing_json_flag(self, text: str) -> Optional[bool]:
        """解析分类模型返回的 JSON 行；解析失败返回 None。"""
        if not text or not str(text).strip():
            return None
        raw = str(text).strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
            raw = re.sub(r"\s*```\s*$", "", raw)
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict) and "in_ride_hailing" in obj:
                return bool(obj.get("in_ride_hailing"))
        except Exception:
            pass
        return None

    def _llm_is_ride_hailing_scenario(self, dialogue_snippet: str) -> bool:
        """
        使用项目 `get_llm_config()` 中的主力模型判断对话片段是否应按网约车/叫车流程处理。
        失败时保守返回 False。
        """
        try:
            from ty_mem_agent.config.settings import get_llm_config
            from qwen_agent.llm import get_chat_model
            from qwen_agent.llm.schema import Message as LLMMessage
            from qwen_agent.llm.schema import USER as LLM_USER, SYSTEM as LLM_SYSTEM

            llm_config = dict(get_llm_config())
            llm = get_chat_model(llm_config)
            # qwen3-max 等会启用 use_raw_api，框架要求 full stream（stream=True, delta_stream=False）
            use_stream = bool(getattr(llm, "use_raw_api", False))

            system_prompt = (
                "你是对话场景分类器。根据下面「对话片段」（旧到新，可能含用户与助手），"
                "判断当前应处理的业务是否属于网约车/叫车相关流程。\n"
                "属于的情况包括：用户要叫车、去某地、补充上车点或目的地、补充联系方式、"
                "选择车型或价格档、确认/取消叫车、查询进行中的用车订单等。\n"
                "不属于的情况包括：与叫车无关的天气、闲聊、纯资讯、与出行叫车无关的地图或搜索等。\n"
                "请仅依据对话语义与上下文判断，不要臆测未出现的信息。\n"
                "只输出一行 JSON，且必须是以下二者之一，不要输出其他任何字符：\n"
                '{"in_ride_hailing": true}\n'
                "或\n"
                '{"in_ride_hailing": false}'
            )
            user_content = f"对话片段：\n{dialogue_snippet}"

            messages = [
                LLMMessage(role=LLM_SYSTEM, content=system_prompt),
                LLMMessage(role=LLM_USER, content=user_content),
            ]
            response_text = ""
            out = llm.chat(messages=messages, stream=use_stream, delta_stream=False)
            if use_stream:
                for responses in out:
                    if not responses:
                        continue
                    last = responses[-1] if isinstance(responses, list) else responses
                    if hasattr(last, "content") and last.content:
                        response_text = (
                            last.content
                            if isinstance(last.content, str)
                            else str(last.content)
                        )
            else:
                responses = out
                if responses:
                    last = responses[-1] if isinstance(responses, list) else responses
                    if hasattr(last, "content") and last.content:
                        response_text = (
                            last.content
                            if isinstance(last.content, str)
                            else str(last.content)
                        )

            parsed = self._parse_ride_hailing_json_flag(response_text)
            result = bool(parsed) if parsed is not None else False
            logger.debug(
                f"打车场景 LLM 分类: snippet_len={len(dialogue_snippet)}, "
                f"raw={response_text[:120]!r}, result={result}"
            )
            return result
        except Exception as e:
            logger.debug(f"打车场景 LLM 分类失败: {e}")
            return False
