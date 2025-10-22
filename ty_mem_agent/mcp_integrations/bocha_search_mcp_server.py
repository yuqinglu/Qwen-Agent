"""
Bocha Search MCP Server 配置
基于标准 MCP 协议连接博查AI搜索引擎
参考文档: https://bocha-ai.feishu.cn/wiki/DCZTwH6OMidCbTkWFRVcVkHonag
"""

import os
from typing import Dict, Optional, List
from qwen_agent.tools.base import BaseTool
from ty_mem_agent.utils.logger_config import get_logger
from ty_mem_agent.mcp_integrations.tool_wrapper import LoggingToolWrapper
# from .tool_wrapper import LoggingToolWrapper

logger = get_logger("BochaSearchMCPServer")


def get_bocha_search_mcp_server_config(api_key: Optional[str] = None) -> Dict:
    """
    获取博查搜索 MCP Server 配置
    
    Args:
        api_key: 博查搜索 API Key，如果不提供则从环境变量 BOCHA_API_KEY 读取
        
    Returns:
        MCP Server 配置字典，用于 QwenAgent MCPManager
        
    Example:
        >>> config = get_bocha_search_mcp_server_config()
        >>> # 配置格式：
        >>> # {
        >>> #     "mcpServers": {
        >>> #         "bocha-search": {
        >>> #             "url": "https://mcp.bochaai.com/sse",
        >>> #             "headers": {
        >>> #                 "Authorization": "Bearer sk-****"
        >>> #             }
        >>> #         }
        >>> #     }
        >>> # }
    """
    api_key = api_key or os.environ.get('BOCHA_API_KEY', '')
    
    if not api_key:
        raise ValueError(
            "博查搜索 API Key 未配置！\n"
            "请在环境变量中设置 BOCHA_API_KEY 或在调用时传入 api_key 参数\n"
            "获取 Key: https://bocha-ai.feishu.cn/wiki/DCZTwH6OMidCbTkWFRVcVkHonag"
        )
    
    # 根据博查官方文档和 QwenAgent MCPManager 的要求配置
    # 必须包含外层的 "mcpServers" 键
    config = {
        "mcpServers": {
            "bocha-search": {
                "url": "https://mcp.bochaai.com/sse",
                "headers": {
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "text/event-stream"
                }
            }
        }
    }
    
    logger.info("✅ 博查搜索 MCP Server 配置已生成")
    logger.info(f"   Server URL: https://mcp.bochaai.com/sse")
    logger.info(f"   API Key: {api_key[:8]}...{api_key[-4:] if len(api_key) > 12 else '****'}")
    
    return config


class BochaSearchMCPServerManager:
    """博查搜索 MCP Server 管理器"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(BochaSearchMCPServerManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.mcp_manager = None
            self.tools: List[BaseTool] = []
            self.original_tools: List[BaseTool] = []  # 保存原始工具
            self._initialized = True
    
    def initialize(self, api_key: Optional[str] = None) -> None:
        """
        初始化博查搜索 MCP Server 连接
        
        Args:
            api_key: 博查搜索 API Key
        """
        # 如果已经初始化过，不重复初始化
        if self.tools:
            logger.debug(f"✅ 博查搜索 MCP Server 已初始化，跳过重复初始化")
            return
        
        try:
            from qwen_agent.tools.mcp_manager import MCPManager
        except ImportError as e:
            logger.error("❌ 无法导入 MCPManager，请安装 mcp: pip install -U mcp")
            raise ImportError("需要安装 mcp: pip install -U mcp") from e
        
        # 获取配置
        mcp_config = get_bocha_search_mcp_server_config(api_key)
        
        # 初始化 MCP Manager
        logger.info("🔍 正在连接博查搜索 MCP Server...")
        self.mcp_manager = MCPManager()
        
        try:
            # 初始化 MCP 连接并获取工具
            self.original_tools = self.mcp_manager.initConfig(mcp_config)
            
            if self.original_tools:
                # 包装工具以添加日志记录
                self.tools = []
                for tool in self.original_tools:
                    wrapped_tool = LoggingToolWrapper(tool)
                    self.tools.append(wrapped_tool)
                
                logger.info(f"✅ 博查搜索 MCP Server 连接成功，获取到 {len(self.tools)} 个工具")
                
                # 记录可用工具
                for tool in self.tools:
                    logger.info(f"   📋 工具: {tool.name} - {getattr(tool, 'description', '无描述')}")
                    
            else:
                logger.warning("⚠️ 博查搜索 MCP Server 连接成功，但未获取到工具")
                
        except Exception as e:
            logger.error(f"❌ 博查搜索 MCP Server 连接失败: {e}")
            raise e
    
    def get_tools(self) -> List[BaseTool]:
        """获取博查搜索工具列表"""
        if not self.tools:
            self.initialize()
        return self.tools
    
    def get_web_search_tool(self) -> Optional[BaseTool]:
        """
        获取Web搜索工具（只返回Web搜索，不返回AI搜索）
        
        优先级：
        1. 只买了Web搜索流量
        2. AI搜索单价更贵
        3. 大部分场景Web搜索够用
        """
        tools = self.get_tools()
        for tool in tools:
            tool_name = getattr(tool, 'name', '').lower()
            # 只匹配Web搜索，排除AI搜索
            if 'web' in tool_name and 'search' in tool_name:
                logger.info(f"🎯 选择Web搜索: {tool.name}")
                return tool
        
        # 如果没找到Web搜索，记录警告
        logger.warning("⚠️  未找到Web搜索工具")
        if tools:
            logger.warning(f"   可用工具: {[t.name for t in tools]}")
        return None
    
    def cleanup(self):
        """清理资源"""
        if self.mcp_manager:
            try:
                self.mcp_manager.shutdown()
                logger.info("✅ 博查搜索 MCP Server 已关闭")
            except Exception as e:
                logger.warning(f"⚠️ 关闭博查搜索 MCP Server 时出错: {e}")
        
        self.tools = []
        self.original_tools = []


# 全局实例
_bocha_search_manager = None


def get_bocha_search_mcp_manager(api_key: Optional[str] = None) -> BochaSearchMCPServerManager:
    """获取博查搜索 MCP Manager 实例"""
    global _bocha_search_manager
    if _bocha_search_manager is None:
        _bocha_search_manager = BochaSearchMCPServerManager()
    return _bocha_search_manager


def register_bocha_web_search_only(api_key: Optional[str] = None) -> Optional[BaseTool]:
    """
    只注册Web搜索工具（推荐）
    
    原因：
    1. 只买了Web搜索流量
    2. AI搜索单价更贵
    3. 大部分场景Web搜索够用
    """
    manager = get_bocha_search_mcp_manager(api_key)
    return manager.get_web_search_tool()


def shutdown_bocha_search_mcp():
    """关闭博查搜索 MCP 连接"""
    global _bocha_search_manager
    if _bocha_search_manager:
        _bocha_search_manager.cleanup()
        _bocha_search_manager = None
        logger.info("✅ 博查搜索 MCP 连接已关闭")


if __name__ == "__main__":
    # 测试配置
    try:
        config = get_bocha_search_mcp_server_config()
        print("✅ 博查搜索 MCP 配置测试通过")
        print(f"配置: {config}")
    except Exception as e:
        print(f"❌ 配置测试失败: {e}")
