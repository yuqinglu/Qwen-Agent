"""
Stock Query MCP Server 配置
阿里云百炼股票查询服务
提供股票查询、行情查询等功能
使用 Streamable HTTP Endpoint 方式集成
参考文档: https://bailian.console.aliyun.com/?tab=mcp#/mcp-market/detail/market-cmapi00065924
"""

import os
from typing import Dict, Optional, List
from qwen_agent.tools.base import BaseTool
from ty_mem_agent.utils.logger_config import get_logger
from ty_mem_agent.mcp_integrations.tool_wrapper import LoggingToolWrapper

logger = get_logger("StockMCPServer")


def get_stock_mcp_server_config(api_key: Optional[str] = None) -> Dict:
    """
    获取股票查询 MCP Server 配置
    
    Args:
        api_key: DashScope API Key，如果不提供则从环境变量 DASHSCOPE_API_KEY 读取
        
    Returns:
        MCP Server 配置字典，用于 QwenAgent MCPManager
        
    Example:
        >>> config = get_stock_mcp_server_config()
        >>> # 配置格式：
        >>> # {
        >>> #     "mcpServers": {
        >>> #         "stock-query": {
        >>> #             "type": "streamable-http",
        >>> #             "url": "https://dashscope.aliyuncs.com/api/v1/mcps/market-cmapi00065924/mcp",
        >>> #             "headers": {
        >>> #                 "Authorization": "Bearer sk-****"
        >>> #             }
        >>> #         }
        >>> #     }
        >>> # }
    """
    # 优先使用传入的api_key，然后尝试从settings获取，最后从环境变量获取
    if not api_key:
        try:
            from ty_mem_agent.config.settings import settings
            api_key = getattr(settings, 'DASHSCOPE_API_KEY', None)
        except ImportError:
            pass
        
        if not api_key:
            api_key = os.environ.get('DASHSCOPE_API_KEY', '')
    
    if not api_key:
        raise ValueError(
            "DashScope API Key 未配置！\n"
            "请在环境变量中设置 DASHSCOPE_API_KEY 或在调用时传入 api_key 参数\n"
            "获取 Key: 访问 https://bailian.console.aliyun.com 申请"
        )
    
    # 根据阿里云百炼文档配置
    # 使用 streamable-http 类型，在 headers 中传递 API Key
    config = {
        "mcpServers": {
            "stock-query": {
                "type": "streamable-http",
                "url": "https://dashscope.aliyuncs.com/api/v1/mcps/market-cmapi00065924/mcp",
                "sse_read_timeout": 300,
                "headers": {
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "text/event-stream"
                }
            }
        }
    }
    
    logger.info("✅ 股票查询 MCP Server 配置已生成")
    logger.info(f"   Server URL: https://dashscope.aliyuncs.com/api/v1/mcps/market-cmapi00065924/mcp")
    logger.info(f"   Connection Type: Streamable HTTP")
    logger.info(f"   API Key: {api_key[:8]}...{api_key[-4:] if len(api_key) > 12 else '****'}")
    
    return config


class StockMCPServerManager:
    """股票查询 MCP Server 管理器"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(StockMCPServerManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.mcp_manager = None
            self.tools: List[BaseTool] = []
            self.original_tools: List[BaseTool] = []  # 保存原始工具
            self._initialized = True
    
    def initialize(self, api_key: Optional[str] = None) -> None:
        """
        初始化股票查询 MCP Server 连接
        
        Args:
            api_key: DashScope API Key
        """
        # 如果已经初始化过，不重复初始化
        if self.tools:
            logger.debug(f"✅ 股票查询 MCP Server 已初始化，跳过重复初始化")
            return
        
        try:
            from qwen_agent.tools.mcp_manager import MCPManager
        except ImportError as e:
            logger.error("❌ 无法导入 MCPManager，请安装 mcp: pip install -U mcp")
            raise ImportError("需要安装 mcp: pip install -U mcp") from e
        
        # 获取配置
        mcp_config = get_stock_mcp_server_config(api_key)
        
        # 初始化 MCP Manager
        logger.info("📈 正在连接股票查询 MCP Server...")
        self.mcp_manager = MCPManager()
        
        try:
            # 初始化 MCP 连接并获取工具
            self.original_tools = self.mcp_manager.initConfig(mcp_config)
            
            if self.original_tools:
                # 过滤掉A股K线复权工具（一般不需要复权功能）
                filtered_tools = []
                excluded_tools = []
                
                for tool in self.original_tools:
                    # 排除A股K线复权工具
                    if 'A股K线复权' in tool.name:
                        excluded_tools.append(tool.name)
                        logger.debug(f"   🚫 排除工具: {tool.name} (复权功能，一般不需要)")
                        continue
                    filtered_tools.append(tool)
                
                # 包装工具以添加日志记录
                self.tools = []
                for tool in filtered_tools:
                    wrapped_tool = LoggingToolWrapper(tool)
                    self.tools.append(wrapped_tool)
                
                logger.info(f"✅ 股票查询 MCP Server 连接成功，获取到 {len(self.tools)} 个工具")
                if excluded_tools:
                    logger.info(f"   🚫 已排除 {len(excluded_tools)} 个工具: {', '.join(excluded_tools)}")
                
                # 记录可用工具
                for tool in self.tools:
                    logger.info(f"   📋 工具: {tool.name} - {getattr(tool, 'description', '无描述')}")
                    
            else:
                logger.warning("⚠️ 股票查询 MCP Server 连接成功，但未获取到工具")
                
        except Exception as e:
            logger.error(f"❌ 股票查询 MCP Server 连接失败: {e}")
            raise e
    
    def get_tools(self) -> List[BaseTool]:
        """获取股票查询工具列表"""
        if not self.tools:
            self.initialize()
        return self.tools
    
    def cleanup(self):
        """清理资源"""
        if self.mcp_manager:
            try:
                self.mcp_manager.shutdown()
                logger.info("✅ 股票查询 MCP Server 已关闭")
            except Exception as e:
                logger.warning(f"⚠️ 关闭股票查询 MCP Server 时出错: {e}")
        
        self.tools = []
        self.original_tools = []


# 全局实例
_stock_manager = None


def get_stock_mcp_manager(api_key: Optional[str] = None) -> StockMCPServerManager:
    """获取股票查询 MCP Manager 实例"""
    global _stock_manager
    if _stock_manager is None:
        _stock_manager = StockMCPServerManager()
    return _stock_manager


def register_stock_tools(api_key: Optional[str] = None) -> List[BaseTool]:
    """
    注册股票查询工具
    
    Args:
        api_key: DashScope API Key
        
    Returns:
        股票查询工具列表
    """
    manager = get_stock_mcp_manager(api_key)
    manager.initialize(api_key)
    return manager.get_tools()


def shutdown_stock_mcp():
    """关闭股票查询 MCP 连接"""
    global _stock_manager
    if _stock_manager:
        _stock_manager.cleanup()
        _stock_manager = None
        logger.info("✅ 股票查询 MCP 连接已关闭")


if __name__ == "__main__":
    # 测试配置
    try:
        config = get_stock_mcp_server_config()
        print("✅ 股票查询 MCP 配置测试通过")
        print(f"配置: {config}")
    except Exception as e:
        print(f"❌ 配置测试失败: {e}")

