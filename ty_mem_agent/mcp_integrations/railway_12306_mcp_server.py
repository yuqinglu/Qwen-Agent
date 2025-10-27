#!/usr/bin/env python3
"""
12306铁路票务查询 MCP Server 集成模块
基于标准 MCP 协议的12306票务查询服务
参考: https://github.com/Joooook/12306-mcp
"""

from typing import Dict, List, Optional, Any
from loguru import logger

from qwen_agent.tools.base import BaseTool
from qwen_agent.tools.mcp_manager import MCPManager


def get_railway_12306_mcp_server_config() -> Dict[str, Any]:
    """获取12306 MCP Server 配置"""
    return {
        "mcpServers": {
            "12306-mcp": {
                "command": "npx",
                "args": [
                    "-y",
                    "12306-mcp"
                ],
                "description": "12306铁路票务查询服务"
            }
        }
    }




class Railway12306MCPServerManager:
    """12306铁路票务查询 MCP Server 管理器"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Railway12306MCPServerManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.mcp_manager = None
            self.tools: List[BaseTool] = []
            self.original_tools: List[BaseTool] = []
            self._initialized = True
    
    def initialize(self) -> None:
        """初始化12306 MCP Server 连接（仅支持stdio模式）"""
        # 如果已经初始化过，不重复初始化
        if self.tools:
            logger.debug(f"✅ 12306 MCP Server 已初始化，跳过重复初始化")
            return
        
        try:
            logger.info("🚄 正在连接12306 MCP Server...")
            self.mcp_manager = MCPManager()
            
            # 获取配置
            mcp_config = get_railway_12306_mcp_server_config()
            
            # 初始化 MCP 连接并获取工具
            self.original_tools = self.mcp_manager.initConfig(mcp_config)
            
            if self.original_tools:
                # 过滤掉不需要的工具
                self.tools = self._filter_tools(self.original_tools)
                logger.info(f"✅ 12306 MCP Server 连接成功，获取到 {len(self.original_tools)} 个工具，过滤后保留 {len(self.tools)} 个工具")
            else:
                raise Exception("12306 MCP Server 连接成功，但未获取到工具")
                
        except Exception as e:
            logger.error(f"❌ 12306 MCP Server 连接失败: {e}")
            raise Exception(f"无法连接到12306 MCP Server: {e}")
    
    def _filter_tools(self, tools: List[BaseTool]) -> List[BaseTool]:
        """过滤掉不需要的12306工具"""
        # 需要移除的工具名称
        excluded_tools = {
            "12306-mcp-get-current-date",
            "12306-mcp-get-station-by-telecode", 
            "12306-mcp-list_resources",
            "12306-mcp-read_resource"
        }
        
        filtered_tools = []
        for tool in tools:
            tool_name = getattr(tool, 'name', '')
            if tool_name not in excluded_tools:
                filtered_tools.append(tool)
        
        logger.info(f"🔧 工具过滤完成: 原始 {len(tools)} 个 -> 过滤后 {len(filtered_tools)} 个")
        return filtered_tools
    
    def get_tools(self) -> List[BaseTool]:
        """获取12306查询工具列表"""
        if not self.tools:
            self.initialize()
        return self.tools
    
    def get_ticket_search_tool(self) -> Optional[BaseTool]:
        """获取票务查询工具"""
        tools = self.get_tools()
        for tool in tools:
            if hasattr(tool, 'name') and '12306' in tool.name.lower():
                return tool
        return tools[0] if tools else None
    
    def cleanup(self):
        """清理资源"""
        try:
            if self.mcp_manager:
                self.mcp_manager.shutdown()
                logger.info("✅ 12306 MCP Server 连接已关闭")
        except Exception as e:
            logger.warning(f"⚠️ 关闭12306 MCP Server 时出错: {e}")
        finally:
            self.tools = []
            self.original_tools = []


# 全局实例
_railway_12306_mcp_manager = None


def get_railway_12306_mcp_manager() -> Railway12306MCPServerManager:
    """获取12306 MCP Manager 单例"""
    global _railway_12306_mcp_manager
    if _railway_12306_mcp_manager is None:
        _railway_12306_mcp_manager = Railway12306MCPServerManager()
    return _railway_12306_mcp_manager


def shutdown_railway_12306_mcp():
    """关闭12306 MCP 连接"""
    global _railway_12306_mcp_manager
    if _railway_12306_mcp_manager:
        _railway_12306_mcp_manager.cleanup()
        _railway_12306_mcp_manager = None


if __name__ == "__main__":
    # 测试12306 MCP Server连接
    try:
        logger.info("🧪 测试12306 MCP Server连接...")
        manager = get_railway_12306_mcp_manager()
        manager.initialize()
        
        tools = manager.get_tools()
        logger.info(f"✅ 获取到 {len(tools)} 个12306工具")
        
        for tool in tools:
            logger.info(f"工具: {tool.name} - {tool.description}")
        
        # 清理
        shutdown_railway_12306_mcp()
        logger.info("🎉 测试完成！")
        
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
