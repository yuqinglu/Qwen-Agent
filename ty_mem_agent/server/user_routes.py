# -*- coding: utf-8 -*-
"""
用户信息路由：用户资料、日历 ID、统计信息

端点（需要 Bearer Token）：
  GET /user/profile       — 获取用户资料（含记忆摘要）
  GET /user/calendar-id   — 获取日历用户 ID
  GET /user/stats         — 获取用户统计信息
"""

from typing import Callable, Optional

from fastapi import APIRouter, Depends
from loguru import logger

from .auth_routes import get_current_user
from .user_manager import user_manager


def create_user_router(
    get_memory_summary_fn: Optional[Callable] = None,
) -> APIRouter:
    """
    构造用户信息路由器。

    Args:
        get_memory_summary_fn: 可选的异步函数，签名 `async (user_id: str) -> str`，
                                用于在 /user/profile 接口中附加记忆摘要。
    """
    router = APIRouter(prefix="/user", tags=["user"])

    @router.get("/profile")
    async def get_profile(current_user=Depends(get_current_user)):
        """获取用户资料（含记忆摘要）"""
        memory_summary = None
        if get_memory_summary_fn:
            try:
                memory_summary = await get_memory_summary_fn(current_user.user_id)
            except Exception as e:
                logger.debug(f"获取记忆摘要失败（非致命）: {e}")

        if not current_user.calendar_user_id:
            from ty_mem_agent.server.user_id_mapper import UserIdMapper
            calendar_user_id = UserIdMapper.get_calendar_user_id(current_user.user_id)
            user_manager.db.update_user(current_user.user_id, {"calendar_user_id": calendar_user_id})
            current_user.calendar_user_id = calendar_user_id

        return {
            "user_id": current_user.user_id,
            "username": current_user.username,
            "email": current_user.email,
            "created_at": current_user.created_at,
            "last_login": current_user.last_login,
            "calendar_user_id": current_user.calendar_user_id,
            "memory_summary": memory_summary,
        }

    @router.get("/calendar-id")
    async def get_calendar_user_id(current_user=Depends(get_current_user)):
        """获取日历用户 ID（JS 安全字符串格式，避免大整数精度丢失）"""
        from ty_mem_agent.server.user_id_mapper import UserIdMapper

        user_data = user_manager.db.get_user(current_user.user_id)
        if user_data:
            calendar_user_id = user_data.get("calendar_user_id")
            if calendar_user_id:
                current_user.calendar_user_id = calendar_user_id
                logger.debug(f"从数据库加载 calendar_user_id: {current_user.user_id} -> {calendar_user_id}")
            else:
                calendar_user_id = UserIdMapper.get_calendar_user_id(current_user.user_id)
                user_manager.db.update_user(current_user.user_id, {"calendar_user_id": calendar_user_id})
                current_user.calendar_user_id = calendar_user_id
                logger.info(f"生成并保存 calendar_user_id: {current_user.user_id} -> {calendar_user_id}")
        else:
            calendar_user_id = UserIdMapper.get_calendar_user_id(current_user.user_id)
            current_user.calendar_user_id = calendar_user_id
            logger.warning(f"数据库中无用户数据，使用生成的 calendar_user_id: {calendar_user_id}")

        return {"calendar_user_id": str(current_user.calendar_user_id)}

    @router.get("/stats")
    async def get_user_stats(current_user=Depends(get_current_user)):
        """获取用户统计信息"""
        return user_manager.get_user_stats()

    return router
