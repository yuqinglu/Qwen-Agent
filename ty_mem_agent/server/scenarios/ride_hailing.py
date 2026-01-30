# -*- coding: utf-8 -*-
"""
打车场景：阶段与 TTS 时机
- 阶段1：查询电话 → 有电话则进入确认起点终点及价格；无电话则与用户确认电话
- 阶段2：确认起点终点及价格后呼叫车
- 阶段3：司机接单后把车辆信息发送给客户
"""

import json
import re
from typing import Any, Dict, Optional

from .base import ScenarioHandler, ScenarioToolResult


class RideHailingScenario(ScenarioHandler):
    """打车场景：只负责「何时 TTS、何时抑制 TTS」，不负责建卡/发卡。"""

    @property
    def name(self) -> str:
        return "ride_hailing"

    def applies_to(self, user_message: str) -> bool:
        if not user_message or not user_message.strip():
            return False
        msg = user_message.strip()
        keywords = ("叫车", "打车", "叫个车", "帮我叫车", "约车", "网约车")
        return any(k in msg for k in keywords)

    def on_tool_result(
        self,
        tool_name: str,
        tool_result: Any,
        tool_args: Any,
        context: Dict[str, Any],
    ) -> Optional[ScenarioToolResult]:
        if not tool_name:
            return None
        # get_user_profile：决定播报「已查到/请提供电话」，并抑制后续模型 TTS 直到车型卡片
        if tool_name == "get_user_profile" and tool_result is not None:
            tts_to_say = None
            try:
                res = tool_result if isinstance(tool_result, dict) else json.loads(str(tool_result))
                if isinstance(res, dict) and res.get("success"):
                    profile = res.get("profile") if isinstance(res.get("profile"), dict) else None
                    has_phone = False
                    if profile and profile.get("phone"):
                        ph = profile.get("phone")
                        if ph and str(ph).strip():
                            has_phone = True
                    tts_to_say = (
                        "已查到您的电话号码，正在为您查询车型与价格。"
                        if has_phone
                        else "请提供您的电话号码，以便为您叫车。"
                    )
            except Exception:
                pass
            if tts_to_say:
                return ScenarioToolResult(
                    tts_to_say=tts_to_say,
                    suppress_tts_until_cards=True,
                )
            return None

        # Didi-Ride-taxi_estimate：推送车型卡片后应播报「请确认起点终点并选择车型」
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
            return ScenarioToolResult(
                tts_after_ride_confirm_cards=tts_after,
                origin=origin,
                destination=destination,
            )
        return None

    def should_tts_model_output(self, context: Dict[str, Any]) -> bool:
        # 叫车场景：在「已查到/请提供电话」之后、推送车型卡片之前，不 TTS 模型输出
        suppress = context.get("ride_hailing_suppress_tts_until_cards") is True
        pushed = context.get("ride_hailing_pushed_confirm_cards") is True
        if suppress and not pushed:
            return False
        return True
