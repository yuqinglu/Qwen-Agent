#!/usr/bin/env python3
"""
用户ID映射管理器
支持不同MCP服务需要不同格式的userId
"""

import hashlib
from typing import Dict, Optional, Any
from loguru import logger

from ty_mem_agent.utils.logger_config import get_logger

logger = get_logger("UserIdMapper")


class UserIdMapper:
    """用户ID映射管理器
    
    用于管理不同格式的用户ID，支持不同MCP服务的需求
    """
    
    # MCP服务ID类型映射配置
    MCP_USER_ID_TYPES: Dict[str, type] = {
        "calendar": int,  # 日历MCP需要int64
        # 未来可以添加其他MCP服务
        # "other_mcp": str,
    }
    
    @staticmethod
    def generate_calendar_user_id(user_id: str) -> int:
        """生成日历服务的整数用户ID
        
        基于字符串user_id生成稳定的整数ID，确保同一用户总是得到相同的ID
        
        Args:
            user_id: 字符串格式的用户ID
            
        Returns:
            整数格式的用户ID（用于日历MCP服务，在JavaScript安全整数和int64范围内）
        """
        # 使用MD5哈希并转换为整数
        # 取前13位十六进制（确保在JavaScript安全整数范围内：MAX_SAFE_INTEGER = 9007199254740991）
        # 注意：不要改为14位或更多，否则会超出JavaScript安全整数范围！
        hash_obj = hashlib.md5(user_id.encode())
        hex_str = hash_obj.hexdigest()[:13]
        # 转换为整数，确保在JavaScript安全整数和int64范围内
        calendar_user_id = int(hex_str, 16)
        
        # 防御性检查：确保不超过JavaScript安全整数最大值
        max_js_safe = 9007199254740991  # JavaScript Number.MAX_SAFE_INTEGER
        max_int64 = 9223372036854775807  # int64最大值
        
        if calendar_user_id > max_js_safe:
            logger.warning(f"⚠️ calendar_user_id超出JavaScript安全整数范围: {calendar_user_id}，使用取模操作")
            calendar_user_id = calendar_user_id % max_js_safe
        
        # 额外检查：确保不超过int64最大值（虽然13位十六进制不会超出）
        if calendar_user_id > max_int64:
            logger.warning(f"⚠️ calendar_user_id超出int64范围: {calendar_user_id}，使用取模操作")
            calendar_user_id = calendar_user_id % max_int64
        
        # 断言确保结果在JavaScript安全整数和int64范围内（用于开发时调试）
        assert 0 <= calendar_user_id <= max_js_safe, f"calendar_user_id超出JavaScript安全整数范围: {calendar_user_id}"
        assert 0 <= calendar_user_id <= max_int64, f"calendar_user_id超出int64范围: {calendar_user_id}"
        
        logger.debug(f"🔄 生成日历用户ID: {user_id} -> {calendar_user_id}")
        return calendar_user_id
    
    @staticmethod
    def get_mcp_user_id(user_id: str, mcp_service: str) -> Any:
        """获取指定MCP服务需要的用户ID格式
        
        Args:
            user_id: 字符串格式的用户ID（系统内部格式）
            mcp_service: MCP服务名称（如 "calendar"）
            
        Returns:
            对应MCP服务需要的用户ID格式
        """
        if mcp_service not in UserIdMapper.MCP_USER_ID_TYPES:
            logger.warning(f"⚠️ 未知的MCP服务: {mcp_service}，使用默认字符串格式")
            return user_id
        
        target_type = UserIdMapper.MCP_USER_ID_TYPES[mcp_service]
        
        if target_type == int:
            # 日历服务需要整数ID
            return UserIdMapper.generate_calendar_user_id(user_id)
        elif target_type == str:
            # 字符串格式直接返回
            return user_id
        else:
            logger.warning(f"⚠️ 不支持的ID类型: {target_type}，使用默认字符串格式")
            return user_id
    
    @staticmethod
    def get_calendar_user_id(user_id: str) -> int:
        """获取日历服务的用户ID（便捷方法）
        
        Args:
            user_id: 字符串格式的用户ID
            
        Returns:
            整数格式的用户ID
        """
        return UserIdMapper.get_mcp_user_id(user_id, "calendar")

