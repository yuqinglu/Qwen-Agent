# -*- coding: utf-8 -*-
"""
深度思考规划器：在开启 deep_thinking 时，先调用大模型对用户问题做一次任务规划，
得到与问题相关的 plan_text 和 steps，避免固定模板（如一律提手机号、上车地点）。
"""

import json
import re
from typing import Any, Dict, List, Optional

from loguru import logger
from qwen_agent.llm import get_chat_model
from qwen_agent.llm.schema import Message, USER, SYSTEM

from ty_mem_agent.config.settings import get_llm_config


PLANNER_SYSTEM = """你是一个任务规划助手。根据用户的问题（及可选的历史对话），输出助手的执行规划。

核心原则：
- 紧扣用户问题：plan_text 和每步 desc 必须具体提到用户问题的关键信息（地名、日期、人物、事项等）。
- 多轮对话：若提供了「最近几轮对话」，用户当前消息可能是对上一轮助手问题的简短回复（如只发了一个地点名、日期、选项）。此时必须结合上下文理解意图，规划应延续当前任务，而不是把当前消息当成全新独立问题。
  例：上一轮助手问「请问您的上车地点是哪里」，用户本条只发「万科锦绣滨江」→ 表示用户提供上车地点，意图是继续叫车流程（确认起终点、查车型价格等），不要规划成「查询万科锦绣滨江楼盘信息」。
- 不要提及与当前意图无关的业务；不要暴露内部工具名或接口名，用面向用户的业务语言描述。

输出要求：
1. plan_text：一句自然中文，概括助手本回合要为用户做什么，需包含与当前意图相关的关键信息。
2. steps：2～4步，每步为一个对象，包含：
   - type：analysis / tool / generate
   - title：本步骤的小标题，4～12个中文字符左右，例如“分析需求”“查询北京明日天气”“生成最终回复”等
   - desc：对该步骤的详细描述，需包含用户问题中的关键信息（地名/日期/事项等），避免泛泛而谈
3. 只输出一个合法 JSON，无其他文字。

{"plan_text":"...","steps":[{"type":"analysis","title":"...","desc":"..."},{"type":"tool","title":"...","desc":"..."},{"type":"generate","title":"...","desc":"..."}]}"""


def _extract_json_from_content(content: str) -> Optional[Dict[str, Any]]:
    """从模型输出中提取 JSON 对象（允许被 markdown 代码块包裹）。"""
    if not content or not content.strip():
        return None
    text = content.strip()
    # 去掉 ```json ... ``` 或 ``` ... ```
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试找第一个 { ... } 子串
        start = text.find("{")
        if start >= 0:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except json.JSONDecodeError:
                            break
    return None


def plan_with_llm(
    user_message: str,
    timeout_seconds: float = 15.0,
    recent_dialogue: Optional[List[Dict[str, str]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    用大模型对用户问题做一次任务规划，返回 plan_text 与 steps。
    在同步上下文中调用；若在 async 中请用 asyncio.to_thread(plan_with_llm, ...)。

    Args:
        user_message: 用户当前本条消息。
        timeout_seconds: 未使用，保留兼容。
        recent_dialogue: 最近几轮对话 [{"role":"user"|"assistant","content":"..."}]，不含本条。
                         用于多轮场景下理解简短回复（如用户只回「万科锦绣滨江」表示上车地点）。

    Returns:
        {"plan_text": str, "steps": [{"type": str, "title": str, "desc": str}, ...]} 或 None（失败时）
    """
    if not user_message or not user_message.strip():
        return None
    try:
        llm_config = get_llm_config()
        if llm_config.get("model_type") == "qwen_dashscope":
            llm_config = {**llm_config, "model": "qwen-plus"}
        llm = get_chat_model(llm_config)

        # 若有历史对话，拼成上下文，避免把简短回复误判成新意图（如「万科锦绣滨江」当楼盘查询）
        context_block = ""
        if recent_dialogue:
            lines = []
            for m in recent_dialogue:
                role = (m.get("role") or "").strip().lower()
                content = (m.get("content") or "").strip()
                if not content:
                    continue
                label = "助手" if role == "assistant" else "用户"
                lines.append(f"{label}：{content}")
            if lines:
                context_block = "最近几轮对话（不含本条）：\n" + "\n".join(lines) + "\n\n"

        user_content = (
            f"{context_block}用户当前本条消息：「{user_message.strip()}」\n"
            "请结合上下文（若有）理解用户意图，输出本回合执行规划的 JSON。"
        )
        messages = [
            Message(role=SYSTEM, content=PLANNER_SYSTEM),
            Message(role=USER, content=user_content),
        ]
        response_content = ""
        for responses in llm.chat(messages=messages, stream=False):
            if responses:
                last = responses[-1] if isinstance(responses, list) else responses
                if hasattr(last, "content") and last.content:
                    response_content = last.content if isinstance(last.content, str) else str(last.content)
                    break
        if not response_content:
            logger.warning("深度思考规划器：模型返回为空")
            return None
        out = _extract_json_from_content(response_content)
        if not out or not isinstance(out, dict):
            logger.warning("深度思考规划器：解析 JSON 失败")
            return None
        plan_text = out.get("plan_text")
        steps = out.get("steps")
        if not plan_text or not isinstance(plan_text, str):
            logger.warning("深度思考规划器：缺少 plan_text")
            return None
        if not steps or not isinstance(steps, list) or len(steps) < 2:
            logger.warning("深度思考规划器：steps 无效或过少")
            return None
        # 规范化 steps
        allowed_types = ("analysis", "tool", "generate", "update")
        normalized = []
        for i, s in enumerate(steps):
            if not isinstance(s, dict):
                continue
            t = (s.get("type") or "tool").strip().lower()
            if t not in allowed_types:
                t = "tool"
            d = (s.get("desc") or "").strip() or "执行该步骤"
            raw_title = (s.get("title") or "").strip()
            if not raw_title:
                # 根据类型给一个简短兜底标题
                if t == "analysis":
                    raw_title = "分析需求"
                elif t == "tool":
                    raw_title = "调用工具"
                elif t in ("generate", "update"):
                    raw_title = "生成回复"
                else:
                    raw_title = "执行步骤"
            normalized.append({"type": t, "title": raw_title, "desc": d})
        if len(normalized) < 2:
            return None
        return {"plan_text": plan_text.strip(), "steps": normalized}
    except Exception as e:
        logger.warning(f"深度思考规划器调用失败: {e}")
        return None
