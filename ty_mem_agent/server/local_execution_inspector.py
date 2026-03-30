# -*- coding: utf-8 -*-
"""
本地执行结果检测器

判断本地 Agent 执行结果是否表示"无法完成"，触发 OpenClaw 兜底。
触发路径：
  1. LLM 自评路径 — 最终文本含无能力语义（"我无法…"/"这超出了我的…" 等，正则匹配）
  2. 执行异常路径 — 超时、抛出异常

说明：「周期性/定时」是否在对话开头直通 OpenClaw，由 task_capability_evaluator +
recurring_intent_llm 用 LLM 判定，不再在本文件用正则推断 cron。
"""

import re
from dataclasses import dataclass
from typing import Optional

from loguru import logger

from ty_mem_agent.config.settings import settings


# ---------------------------------------------------------------------------
# 无能力关键词列表（匹配本地 LLM 输出表示自身无法完成的句子）
# ---------------------------------------------------------------------------

_INABILITY_PATTERNS = [
    r"我(目前|暂时|现在)?无法",
    r"我(目前|暂时|现在)?不能",
    r"我(目前|暂时)?没有(办法|能力|权限|途径)",
    r"这(超出|不在)(了?)我的(能力|范围|权限)",
    r"我(目前|暂时)?不支持(定期|周期|持续|长期|自动)",
    r"我没有(定期|周期|持续|长期|自动)执行",
    r"我不(具备|拥有)(定期|周期|持续|长期|自动)",
    r"抱歉.*无法",
    r"很遗憾.*无法",
    r"我(目前|暂时)?做不到",
    r"超出了?(我的)?能力范围",
    r"我(当前|目前)的能力(不支持|无法|不足以)",
    r"无法(为您)?完成(这个|该|此)(任务|请求|需求)",
    r"我(目前|暂时)?无法(定期|自动|持续|主动)(执行|完成|发送|推送|通知)",
    r"建议您使用.*(定时|提醒|日历|计划)",
]

_INABILITY_RE = [re.compile(p) for p in _INABILITY_PATTERNS]


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class InspectionResult:
    """本地执行结果检测结论"""

    should_fallback: bool
    """是否需要转交 OpenClaw"""

    fallback_reason: Optional[str] = None
    """触发原因：inability_response | llm_periodic_intent | execution_error | timeout 等"""

    local_result: Optional[str] = None
    """本地已生成的部分结果（如有），可先发给用户再提交 OpenClaw"""

    openclaw_task_type: str = "one_time"
    """OpenClaw 任务类型：periodic | research | one_time"""

    suggested_schedule: Optional[str] = None
    """建议的 cron 表达式，仅 periodic 类型有意义（如 "0 16 * * 1-5"）"""

    skip_local: bool = False
    """快速预判阶段：是否跳过本地执行直通 OpenClaw"""

    periodic_description: Optional[str] = None
    """周期性任务的人类可读描述（如"每天执行"）"""


# ---------------------------------------------------------------------------
# 核心检测函数
# ---------------------------------------------------------------------------

def detect_inability_in_response(text: str) -> bool:
    """
    检测 LLM 输出文本是否含有表示无能力的语义。
    使用预编译正则列表，纯内存操作，无 IO。
    """
    if not text:
        return False
    for pattern in _INABILITY_RE:
        if pattern.search(text):
            logger.debug(f"[LocalInspector] 无能力关键词命中: pattern={pattern.pattern}")
            return True
    return False


def inspect_execution_result(
    local_result: Optional[str],
    error: Optional[Exception],
    elapsed_ms: float,
    timeout_ms: float = 120_000,
) -> InspectionResult:
    """
    综合三路径判断本地执行结果，输出是否需要转交 OpenClaw。

    Args:
        local_result: 本地 Agent 最终输出文本（若为空表示未产出）
        error: 执行过程中抛出的异常（若无则为 None）
        elapsed_ms: 本地执行耗时（毫秒）
        timeout_ms: 超时阈值（毫秒），默认 120s

    Returns:
        InspectionResult
    """
    if not settings.OPENCLAW_ENABLED:
        return InspectionResult(should_fallback=False, local_result=local_result)

    # 路径3：执行超时
    if elapsed_ms >= timeout_ms:
        logger.info(f"[LocalInspector] 本地执行超时 elapsed={elapsed_ms:.0f}ms >= {timeout_ms:.0f}ms，触发兜底")
        return InspectionResult(
            should_fallback=True,
            fallback_reason="timeout",
            local_result=local_result,
            openclaw_task_type="one_time",
        )

    # 路径3：执行异常
    if error is not None:
        logger.info(f"[LocalInspector] 本地执行异常: {error}，触发兜底")
        return InspectionResult(
            should_fallback=True,
            fallback_reason="execution_error",
            local_result=local_result,
            openclaw_task_type="one_time",
        )

    # 路径1：LLM 自评无能力
    if local_result and detect_inability_in_response(local_result):
        logger.info(f"[LocalInspector] 检测到 LLM 无能力表述，触发兜底")
        return InspectionResult(
            should_fallback=True,
            fallback_reason="inability_response",
            local_result=None,  # 无能力文本不发给用户，由 OpenClaw 接管
            openclaw_task_type="research",
        )

    # 本地成功
    return InspectionResult(
        should_fallback=False,
        local_result=local_result,
    )
