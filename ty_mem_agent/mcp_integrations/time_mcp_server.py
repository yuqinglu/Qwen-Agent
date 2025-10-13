#!/usr/bin/env python3
"""
时间查询 MCP Server 集成模块
基于标准 MCP 协议的时间查询服务
"""

import asyncio
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, timedelta
from loguru import logger

from qwen_agent.tools.base import BaseTool
from qwen_agent.tools.mcp_manager import MCPManager


def get_time_mcp_server_config() -> Dict[str, Any]:
    """获取时间 MCP Server 配置"""
    return {
        "mcpServers": {
            "time": {
                "command": "uvx",
                "args": ["mcp-server-time", "--local-timezone=Asia/Shanghai"],
                "description": "时间查询服务"
            }
        }
    }


class TimeQueryTool(BaseTool):
    """时间查询工具 - 自定义实现作为备选方案"""
    
    name = "time_query"
    description = "查询当前时间和日期信息，支持不同时区和格式"
    parameters = {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "时区，如 'Asia/Shanghai', 'UTC', 'America/New_York' 等，默认为本地时区",
                "default": "local"
            },
            "format": {
                "type": "string", 
                "description": "时间格式，如 'full', 'date', 'time', 'datetime' 等",
                "default": "full"
            },
            "language": {
                "type": "string",
                "description": "语言，'zh' 中文，'en' 英文",
                "default": "zh"
            }
        },
        "required": []
    }
    
    def call(self, params: str, **kwargs) -> str:
        """执行时间查询"""
        try:
            # 解析参数
            if isinstance(params, str):
                params_dict = json.loads(params) if params else {}
            else:
                params_dict = params or {}
            
            timezone_str = params_dict.get("timezone", "local")
            format_type = params_dict.get("format", "full")
            language = params_dict.get("language", "zh")
            
            # 获取当前时间
            if timezone_str == "local":
                now = datetime.now()
            elif timezone_str == "UTC":
                now = datetime.now(timezone.utc)
            else:
                # 尝试解析时区
                try:
                    import pytz
                    tz = pytz.timezone(timezone_str)
                    now = datetime.now(tz)
                except ImportError:
                    logger.warning("pytz 未安装，使用本地时区")
                    now = datetime.now()
                except Exception as e:
                    logger.warning(f"时区解析失败: {e}，使用本地时区")
                    now = datetime.now()
            
            # 根据格式生成结果
            if format_type == "date":
                if language == "zh":
                    result = now.strftime("%Y年%m月%d日")
                else:
                    result = now.strftime("%Y-%m-%d")
            elif format_type == "time":
                if language == "zh":
                    result = now.strftime("%H时%M分%S秒")
                else:
                    result = now.strftime("%H:%M:%S")
            elif format_type == "datetime":
                if language == "zh":
                    result = now.strftime("%Y年%m月%d日 %H时%M分%S秒")
                else:
                    result = now.strftime("%Y-%m-%d %H:%M:%S")
            else:  # full
                if language == "zh":
                    # 中文格式：2024年10月13日 星期日 14时30分25秒
                    weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
                    weekday = weekday_names[now.weekday()]
                    result = f"{now.strftime('%Y年%m月%d日')} {weekday} {now.strftime('%H时%M分%S秒')}"
                else:
                    # 英文格式：Sunday, October 13, 2024 at 2:30:25 PM
                    result = now.strftime("%A, %B %d, %Y at %I:%M:%S %p")
            
            # 添加时区信息
            if timezone_str != "local":
                if language == "zh":
                    result += f" ({timezone_str})"
                else:
                    result += f" ({timezone_str})"
            
            logger.info(f"🕐 时间查询成功: {result}")
            return result
            
        except Exception as e:
            error_msg = f"时间查询失败: {e}"
            logger.error(f"❌ {error_msg}")
            return error_msg


class TimeMCPServerManager:
    """时间查询 MCP Server 管理器"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TimeMCPServerManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.mcp_manager = None
            self.tools: List[BaseTool] = []
            self.original_tools: List[BaseTool] = []  # 保存原始工具
            self._initialized = True
    
    def initialize(self, mode: str = "stdio") -> None:
        """
        初始化时间 MCP Server 连接
        
        Args:
            mode: 连接模式，"stdio" 或 "custom"，默认 "stdio"
        """
        # 如果已经初始化过，不重复初始化
        if self.tools:
            logger.debug(f"✅ 时间 MCP Server 已初始化，跳过重复初始化")
            return
        
        try:
            if mode == "stdio":
                # 尝试使用标准 MCP Server
                from qwen_agent.tools.mcp_manager import MCPManager
                
                logger.info("🕐 正在连接时间 MCP Server...")
                self.mcp_manager = MCPManager()
                
                # 获取配置
                mcp_config = get_time_mcp_server_config()
                
                # 初始化 MCP 连接并获取工具
                self.original_tools = self.mcp_manager.initConfig(mcp_config)
                
                if self.original_tools:
                    self.tools = self.original_tools
                    logger.info(f"✅ 时间 MCP Server 连接成功，获取到 {len(self.tools)} 个工具")
                else:
                    logger.warning("⚠️ 时间 MCP Server 连接成功，但未获取到工具，使用自定义工具")
                    self.tools = [TimeQueryTool()]
                    
            else:  # custom mode
                # 使用自定义时间查询工具
                logger.info("🕐 使用自定义时间查询工具...")
                self.tools = [TimeQueryTool()]
                logger.info("✅ 自定义时间查询工具初始化完成")
                
        except ImportError as e:
            logger.warning(f"⚠️ 无法导入 MCPManager: {e}，使用自定义时间工具")
            self.tools = [TimeQueryTool()]
        except Exception as e:
            logger.warning(f"⚠️ 时间 MCP Server 连接失败: {e}，使用自定义时间工具")
            self.tools = [TimeQueryTool()]
    
    def get_tools(self) -> List[BaseTool]:
        """获取时间查询工具列表"""
        if not self.tools:
            self.initialize()
        return self.tools
    
    def cleanup(self):
        """清理资源"""
        try:
            if self.mcp_manager:
                self.mcp_manager.shutdown()
                logger.info("✅ 时间 MCP Server 连接已关闭")
        except Exception as e:
            logger.warning(f"⚠️ 关闭时间 MCP Server 时出错: {e}")
        finally:
            self.tools = []
            self.original_tools = []


# 全局实例
_time_mcp_manager = None


def get_time_mcp_manager() -> TimeMCPServerManager:
    """获取时间 MCP Manager 单例"""
    global _time_mcp_manager
    if _time_mcp_manager is None:
        _time_mcp_manager = TimeMCPServerManager()
    return _time_mcp_manager


def shutdown_time_mcp():
    """关闭时间 MCP 连接"""
    global _time_mcp_manager
    if _time_mcp_manager:
        _time_mcp_manager.cleanup()
        _time_mcp_manager = None


if __name__ == "__main__":
    # 测试时间查询工具
    import asyncio
    
    async def test_time_tools():
        """测试时间工具"""
        logger.info("🧪 测试时间查询工具...")
        
        # 测试自定义工具
        tool = TimeQueryTool()
        
        # 测试不同参数
        test_cases = [
            {"format": "full", "language": "zh"},
            {"format": "date", "language": "zh"},
            {"format": "time", "language": "zh"},
            {"format": "datetime", "language": "en"},
            {"timezone": "UTC", "format": "full", "language": "en"},
        ]
        
        for i, params in enumerate(test_cases, 1):
            logger.info(f"测试 {i}: {params}")
            result = tool.call(json.dumps(params))
            logger.info(f"结果: {result}")
            logger.info("-" * 50)
        
        # 测试 MCP Manager
        logger.info("🧪 测试时间 MCP Manager...")
        manager = get_time_mcp_manager()
        manager.initialize()
        
        tools = manager.get_tools()
        logger.info(f"✅ 获取到 {len(tools)} 个时间工具")
        
        for tool in tools:
            logger.info(f"工具: {tool.name} - {tool.description}")
        
        # 清理
        shutdown_time_mcp()
        logger.info("🎉 测试完成！")
    
    asyncio.run(test_time_tools())
