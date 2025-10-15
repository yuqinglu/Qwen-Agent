#!/usr/bin/env python3
"""
MCP Integrations - 模型上下文协议服务集成模块
注意：此模块名为 mcp_integrations，避免与 PyPI 的 mcp 包命名冲突
"""

from .enhanced_mcp_router import EnhancedMCPRouter, MCPService, MCPRequest, MCPResponse

# 高德地图 - 标准 MCP 协议
from .amap_mcp_server import (
    AmapMCPServerManager,
    get_amap_mcp_server_config,
    get_amap_mcp_manager,
    register_amap_mcp_tools,
    shutdown_amap_mcp
)

# 时间查询 - 标准 MCP 协议 + 自定义工具
from .time_mcp_server import (
    TimeMCPServerManager,
    TimeQueryTool,
    get_time_mcp_manager,
    shutdown_time_mcp
)

# 通用工具包装器
from .tool_wrapper import (
    LoggingToolWrapper,
    RetryToolWrapper,
    CompositeToolWrapper,
    wrap_tool_with_logging,
    wrap_tool_with_retry,
    wrap_tool_with_composite
)

# 工具注册中心
from .tool_registry import (
    ToolRegistry,
    get_tool_registry,
    initialize_tools,
    shutdown_tools
)

__all__ = [
    # MCP Router
    'EnhancedMCPRouter',
    'MCPService',
    'MCPRequest', 
    'MCPResponse',
    
    # 高德地图 MCP Server（标准 MCP 协议）
    'AmapMCPServerManager',
    'get_amap_mcp_server_config',
    'get_amap_mcp_manager',
    'register_amap_mcp_tools',
    'shutdown_amap_mcp',
    
    # 时间查询 MCP Server（标准 MCP 协议 + 自定义工具）
    'TimeMCPServerManager',
    'TimeQueryTool',
    'get_time_mcp_manager',
    'shutdown_time_mcp',
    
    # 通用工具包装器
    'LoggingToolWrapper',
    'RetryToolWrapper',
    'CompositeToolWrapper',
    'wrap_tool_with_logging',
    'wrap_tool_with_retry',
    'wrap_tool_with_composite',
    
    # 工具注册中心
    'ToolRegistry',
    'get_tool_registry',
    'initialize_tools',
    'shutdown_tools',
]
