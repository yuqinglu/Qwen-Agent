# -*- coding: utf-8 -*-
"""
用单次 LLM 调用判断用户是否在请求「周期性/定时自动化任务」，并输出 5 段 cron（多语言）。

不做关键词正则：用户消息可为中文、英文、日文等，由模型理解语义。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from loguru import logger
from qwen_agent.llm import get_chat_model
from qwen_agent.llm.schema import Message, SYSTEM, USER

from ty_mem_agent.config.settings import get_llm_config, settings

from .deep_thinking_planner import _extract_json_from_content
from .local_execution_inspector import InspectionResult

_SYSTEM = """You are a scheduling intent classifier for a personal assistant.

The user message may be in Chinese, English, Japanese, or any language. Understand MEANING, not keywords.

Task: Decide if the user wants a RECURRING / SCHEDULED automation (daily reminder, weekly report, periodic fetch, cron-style job), as opposed to a one-off chat question.

Rules:
1) If they want something to run on a repeating schedule (every day at X, every Monday, each month on the 1st, every hour, etc.), set "is_recurring": true.
2) If it is a single question, chit-chat, or no schedule, set "is_recurring": false.
3) When "is_recurring": true, set "cron" to a standard 5-field cron string:
   minute hour day-of-month month day-of-week
   Use digits, *, -, /, and lists as usual (same as common Unix cron, 5 fields only).
   Examples:
   - Every day at 7:30 (local wall clock): "30 7 * * *"
   - Every weekday 9:00: "0 9 * * 1-5"
   - Every Monday 10:00: "0 10 * * 1"
4) If the user gives a time of day without timezone, assume wall clock in Asia/Shanghai (CST, UTC+8). Map 上午/早上/AM to morning, 下午/PM to afternoon, 晚上 to evening.
5) If recurrence is clear but the exact time is too vague to pick one cron, set "cron" to null and still "is_recurring": true (caller may fall back to local agent).
6) "summary": short human-readable description of the schedule in the SAME language as the user message when possible (max ~40 chars).

Output ONLY one JSON object, no markdown fences, no other text:
{"is_recurring":false,"cron":null,"summary":null}
or
{"is_recurring":true,"cron":"30 7 * * *","summary":"..."}"""


def _is_valid_cron_expression(expr: str) -> bool:
    expr = (expr or "").strip()
    if not expr:
        return False
    parts = expr.split()
    if len(parts) not in (5, 6):
        return False
    return all(bool(p) for p in parts)


def analyze_recurring_intent_llm_sync(user_message: str) -> Optional[InspectionResult]:
    """
    同步调用 LLM。若未配置密钥、解析失败或判定非周期，返回 None。
    """
    if not getattr(settings, "OPENCLAW_PERIODIC_INTENT_LLM_ENABLED", True):
        return None

    if not settings.DASHSCOPE_API_KEY and not settings.OPENAI_API_KEY:
        logger.warning("[RecurringIntentLLM] 未配置 LLM API 密钥，跳过周期性预判")
        return None

    text = (user_message or "").strip()
    if not text:
        return None

    try:
        # 与主聊天 Agent 同源：DEFAULT_LLM_MODEL（DashScope）等，不重绑 plus/turbo/max
        llm_config: Dict[str, Any] = dict(get_llm_config())
    except ValueError as e:
        logger.warning("[RecurringIntentLLM] get_llm_config 失败: {}", e)
        return None

    try:
        llm = get_chat_model(llm_config)
        # qwen3-max 等会启用 use_raw_api，框架要求必须 full stream（stream=True, delta_stream=False）
        use_stream = bool(getattr(llm, "use_raw_api", False))
        messages = [
            Message(role=SYSTEM, content=_SYSTEM),
            Message(role=USER, content=text),
        ]
        response_content = ""
        out = llm.chat(messages=messages, stream=use_stream, delta_stream=False)
        if use_stream:
            for responses in out:
                if not responses:
                    continue
                last = responses[-1] if isinstance(responses, list) else responses
                if hasattr(last, "content") and last.content:
                    response_content = (
                        last.content if isinstance(last.content, str) else str(last.content)
                    )
        else:
            responses = out
            if responses:
                last = responses[-1] if isinstance(responses, list) else responses
                if hasattr(last, "content") and last.content:
                    response_content = (
                        last.content if isinstance(last.content, str) else str(last.content)
                    )
    except Exception as e:
        logger.warning("[RecurringIntentLLM] LLM 调用异常: {}", e)
        return None

    if not response_content.strip():
        logger.warning("[RecurringIntentLLM] 模型返回为空")
        return None

    data = _extract_json_from_content(response_content)
    if not data or not isinstance(data, dict):
        logger.warning("[RecurringIntentLLM] JSON 解析失败: {}", response_content[:200])
        return None

    if not data.get("is_recurring"):
        return None

    cron_raw = data.get("cron")
    cron: Optional[str] = None
    if isinstance(cron_raw, str) and cron_raw.strip():
        cron = cron_raw.strip()
        if not _is_valid_cron_expression(cron):
            logger.warning("[RecurringIntentLLM] cron 字段非法，忽略: {!r}", cron)
            cron = None

    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        summary = "定期执行"
    else:
        summary = summary.strip()

    # 周期意图明确但无法给出合法 cron：不跳过本地，交给主 Agent 追问或处理
    if cron is None:
        logger.info("[RecurringIntentLLM] 判定为周期任务但无有效 cron，改走本地 Agent")
        return None

    logger.info(
        "[RecurringIntentLLM] 命中周期任务: cron={} summary={}",
        cron,
        summary[:80],
    )
    return InspectionResult(
        should_fallback=True,
        fallback_reason="llm_periodic_intent",
        openclaw_task_type="periodic",
        suggested_schedule=cron,
        skip_local=True,
        periodic_description=summary,
    )
