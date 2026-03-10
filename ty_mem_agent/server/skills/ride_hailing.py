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
from typing import Any, Dict, List, Optional

from .base import Skill, SkillInteractionResult


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
      - applies_to 检测叫车意图关键词
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
        """检测叫车意图关键词（仅基于当前这句话）。"""
        if not user_message or not user_message.strip():
            return False
        msg = user_message.strip()
        keywords = ("叫车", "打车", "叫个车", "帮我叫车", "约车", "网约车")
        return any(k in msg for k in keywords)

    def applies_to_with_history(self, history_messages: List[str], current_message: str) -> bool:
        """
        结合最近几轮用户消息 + 当前消息判断是否处于打车场景。

        规则：
        1. 如果当前这句话本身就包含「叫车 / 打车」等关键词 → 直接视为打车场景
        2. 否则，如果当前这句话是补充电话号码（包含“电话/手机号”等，且能解析出 11 位手机号），
           且最近几轮用户消息中曾出现过打车意图 → 也视为仍处于打车场景
        """
        # 1）当前消息本身包含打车意图，则直接命中
        if self.applies_to(current_message):
            return True

        if not history_messages:
            return False

        msg = (current_message or "").strip()
        if not msg:
            return False

        # 2）当前消息是“补充手机号”：
        #    - 不再强依赖中国大陆 11 位格式
        #    - 也不强制要求包含「电话/手机号」等关键词
        #    - 只要本句「明显像一串号码」（数字较多，且整体不太长），并且历史中出现过打车意图，就视为仍在打车场景
        digits = "".join(ch for ch in msg if ch.isdigit())
        # 经验阈值：>=6 位数字，且总长度不过长（避免把长串订单号/地址当成手机号）
        looks_like_phone = len(digits) >= 6 and len(msg) <= 20
        if not looks_like_phone:
            # 辅助判定：包含常见电话类关键词时，适当放宽数字长度要求
            phone_keywords = ("电话", "手机号", "手机号码", "联系电话", "phone", "tel", "mobile")
            if any(k in msg.lower() for k in phone_keywords):
                looks_like_phone = len(digits) >= 3

        if looks_like_phone:
            # 检查最近几轮历史里是否出现过打车意图关键词
            ride_keywords = ("叫车", "打车", "叫个车", "帮我叫车", "约车", "网约车")
            for h in history_messages:
                h_msg = (h or "").strip()
                if any(k in h_msg for k in ride_keywords):
                    return True

        return False

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
