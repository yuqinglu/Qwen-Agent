#!/usr/bin/env python3
"""
日历MCP工具包装器
自动处理user_id到calendar_user_id的转换
"""

import json
from typing import Dict, Any, Optional
from qwen_agent.tools.base import BaseTool
from ty_mem_agent.server.user_manager import user_manager
from ty_mem_agent.server.user_id_mapper import UserIdMapper
from ty_mem_agent.utils.logger_config import get_logger

logger = get_logger("CalendarToolWrapper")


class CalendarToolWrapper(BaseTool):
    """日历MCP工具包装器
    
    自动处理user_id到calendar_user_id的转换
    在调用MCP工具时，自动从kwargs中获取user_id，转换为calendar_user_id并注入到参数中
    """
    
    def __init__(self, original_tool: BaseTool):
        """
        初始化包装器
        
        Args:
            original_tool: 原始的MCP工具
        """
        self.original_tool = original_tool
        self.name = original_tool.name
        self.description = original_tool.description
        self.parameters = original_tool.parameters
        
        # 增强工具描述，说明userId会自动注入
        if "userId" not in self.description.lower():
            self.description = f"{self.description}\n\n【注意】userId参数会自动从用户上下文中获取，无需手动传入。"
        
        # 从工具名称中提取原始工具名（去掉calendar-service-前缀）
        if self.name.startswith("calendar-service-"):
            self.original_tool_name = self.name.replace("calendar-service-", "")
        else:
            self.original_tool_name = self.name
    
    def call(self, params: Any, **kwargs) -> str:
        """
        调用工具，自动处理user_id转换
        
        Args:
            params: 工具参数（可以是字符串或字典）
            **kwargs: 额外参数，包含user_id
            
        Returns:
            工具执行结果
        """
        # 从kwargs中获取user_id
        user_id = kwargs.get("user_id")
        
        if not user_id:
            logger.warning("⚠️ 未提供user_id，无法调用日历工具")
            return json.dumps({
                "success": False,
                "error": "需要提供user_id才能调用日历工具"
            }, ensure_ascii=False)
        
        # 获取用户的calendar_user_id
        try:
            user = user_manager.get_user(user_id)
            if not user:
                logger.warning(f"⚠️ 用户不存在: {user_id}")
                return json.dumps({
                    "success": False,
                    "error": f"用户不存在: {user_id}"
                }, ensure_ascii=False)
            
            # 确保有calendar_user_id
            if not user.calendar_user_id:
                calendar_user_id = UserIdMapper.get_calendar_user_id(user_id)
                # 更新用户信息
                user_manager.db.update_user(user_id, {
                    'calendar_user_id': calendar_user_id
                })
                # 更新内存中的用户对象
                user.calendar_user_id = calendar_user_id
            else:
                calendar_user_id = user.calendar_user_id
            
            logger.debug(f"🔄 用户ID转换: {user_id} -> {calendar_user_id}")
            
        except Exception as e:
            logger.error(f"❌ 获取calendar_user_id失败: {e}")
            return json.dumps({
                "success": False,
                "error": f"获取日历用户ID失败: {str(e)}"
            }, ensure_ascii=False)
        
        # 解析参数
        if isinstance(params, str):
            try:
                params_dict = json.loads(params)
            except json.JSONDecodeError:
                params_dict = {"title": params}  # 如果解析失败，假设是标题
        else:
            params_dict = params.copy() if isinstance(params, dict) else {}
        
        logger.debug(f"📥 原始参数: {json.dumps(params_dict, ensure_ascii=False)[:300]}...")
        
        # MCP工具期望的参数格式是：{"arg0": {...}}
        # 需要确保userId在arg0内部，而不是在顶层
        
        # 提取实际参数（可能在arg0内，也可能在顶层）
        actual_params = None
        if "arg0" in params_dict and isinstance(params_dict["arg0"], dict):
            # 如果参数已经包含arg0包装，提取arg0内的参数
            actual_params = params_dict["arg0"].copy()  # 使用copy避免修改原字典
            logger.debug("📦 检测到arg0包装结构，提取arg0内的参数")
        else:
            # 如果参数不包含arg0，使用顶层参数
            actual_params = params_dict.copy()  # 使用copy避免修改原字典
            logger.debug("📦 参数不包含arg0，使用顶层参数")
        
        # 强制替换参数中的userId，确保使用正确的calendar_user_id
        # 注意：userId应该始终由包装器从用户上下文获取，不应该由Agent或extract_todo工具提供
        existing_user_id = actual_params.get("userId")
        if existing_user_id is not None:
            # 如果参数中已经有userId，记录警告并强制替换
            logger.warning(f"⚠️ 参数中包含userId: {existing_user_id}，将被替换为正确的calendar_user_id: {calendar_user_id}")
        
        # 无条件替换为正确的calendar_user_id（在arg0内部）
        actual_params["userId"] = calendar_user_id
        logger.debug(f"✅ 已在arg0内设置userId: {calendar_user_id}")
        
        # 修复时间格式：确保 rangeStart 和 rangeEnd 符合 RFC3339 格式
        # RFC3339 要求包含时区信息，例如：2025-11-19T00:00:00+08:00
        for time_field in ['rangeStart', 'rangeEnd']:
            if time_field in actual_params:
                time_str = actual_params[time_field]
                if isinstance(time_str, str):
                    # 检查是否已经包含时区信息
                    if not (time_str.endswith('Z') or '+' in time_str or time_str.count('-') > 2):
                        # 没有时区信息，添加 Asia/Shanghai 时区 (+08:00)
                        timezone = actual_params.get('timezone', 'Asia/Shanghai')
                        if timezone == 'Asia/Shanghai':
                            actual_params[time_field] = time_str + '+08:00'
                            logger.debug(f"🕐 修复时间格式: {time_field} = {time_str} -> {actual_params[time_field]}")
                        else:
                            # 其他时区，默认使用 UTC
                            actual_params[time_field] = time_str + 'Z'
                            logger.debug(f"🕐 修复时间格式: {time_field} = {time_str} -> {actual_params[time_field]} (UTC)")
        
        # 最终参数格式：{"arg0": {...}}，userId在arg0内部
        # 无论Agent传入什么格式，最终都统一为 {"arg0": {...}} 格式
        final_params = {"arg0": actual_params}
        
        logger.debug(f"📤 最终参数格式: {json.dumps(final_params, ensure_ascii=False)[:300]}...")
        
        params_dict = final_params
        
        # 调用原始工具
        try:
            # MCP工具期望接收JSON字符串格式的参数
            # 将更新后的字典转换为JSON字符串
            updated_params = json.dumps(params_dict, ensure_ascii=False)
            
            logger.debug(f"📤 调用日历工具: {self.name}, 参数: {updated_params[:200]}...")
            
            result = self.original_tool.call(updated_params, **kwargs)
            
            logger.debug(f"📥 日历工具返回结果: {str(result)[:200]}...")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ 调用日历工具失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return json.dumps({
                "success": False,
                "error": f"调用日历工具失败: {str(e)}"
            }, ensure_ascii=False)


def wrap_calendar_tools(tools: list) -> list:
    """
    包装日历MCP工具列表，自动处理user_id转换
    
    Args:
        tools: 原始工具列表
        
    Returns:
        包装后的工具列表
    """
    wrapped_tools = []
    for tool in tools:
        wrapped_tool = CalendarToolWrapper(tool)
        wrapped_tools.append(wrapped_tool)
        logger.debug(f"✅ 已包装日历工具: {tool.name}")
    
    return wrapped_tools

