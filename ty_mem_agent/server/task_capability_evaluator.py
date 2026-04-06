# -*- coding: utf-8 -*-
"""
任务能力预判（OpenClaw 快速通路）

周期性/定时意图：通过单次 LLM 解析多语言消息，得到 5 段 cron，避免正则无法覆盖
「7点半」「every morning」日文等情况。

与 local_execution_inspector.py 的分工：
  - 本文件：pre-execution 阶段，LLM 判定是否「周期任务且可给出合法 cron」→ 跳过本地直通 OpenClaw
  - local_execution_inspector.py：post-execution 阶段，对本地执行结果做兜底检测（仍含无能力正则）
"""

import asyncio
from typing import Optional

from loguru import logger

from ty_mem_agent.config.settings import settings

from .local_execution_inspector import InspectionResult
from .recurring_intent_llm import analyze_recurring_intent_llm_sync


async def quick_pre_check_async(user_message: str) -> InspectionResult:
    """
    对用户消息做预判：若 LLM 判定为带明确 cron 的周期任务，则 skip_local=True 直通 OpenClaw。

    LLM 失败/超时/无密钥时返回 skip_local=False，走本地主 Agent。
    """
    if not settings.OPENCLAW_ENABLED:
        return InspectionResult(should_fallback=False, skip_local=False)

    if not user_message or not user_message.strip():
        return InspectionResult(should_fallback=False, skip_local=False)

    timeout = float(getattr(settings, "OPENCLAW_PERIODIC_INTENT_LLM_TIMEOUT_SEC", 15.0))

    try:
        periodic_result = await asyncio.wait_for(
            asyncio.to_thread(analyze_recurring_intent_llm_sync, user_message.strip()),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "[TaskEvaluator] 周期性 LLM 预判超时 (%.1fs)，回退本地执行",
            timeout,
        )
        return InspectionResult(should_fallback=False, skip_local=False)
    except Exception as e:
        logger.warning(f"[TaskEvaluator] 周期性 LLM 预判异常: {e}")
        return InspectionResult(should_fallback=False, skip_local=False)

    if periodic_result and periodic_result.skip_local:
        logger.info(
            f"[TaskEvaluator] LLM 命中周期任务: reason={periodic_result.fallback_reason}, "
            f"schedule={periodic_result.suggested_schedule}, desc={periodic_result.periodic_description}"
        )
        return periodic_result

    return InspectionResult(should_fallback=False, skip_local=False)
