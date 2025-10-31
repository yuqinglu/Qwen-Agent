"""
Didi MCP Server 配置
滴滴出行叫车服务
提供叫车、订单查询、价格估算等功能
支持生产环境和调试环境切换
"""

import os
from typing import Dict, Optional, List
from qwen_agent.tools.base import BaseTool
from ty_mem_agent.utils.logger_config import get_logger
from ty_mem_agent.mcp_integrations.tool_wrapper import LoggingToolWrapper

logger = get_logger("DidiMCPServer")


def get_didi_mcp_server_config(api_key: Optional[str] = None, mode: str = "production") -> Dict:
    """
    获取滴滴 MCP Server 配置
    
    Args:
        api_key: 滴滴 API Key，如果不提供则从环境变量 DIDI_API_KEY 读取
        mode: 运行模式，"production" 或 "sandbox"，默认 "production"
        
    Returns:
        MCP Server 配置字典
    """
    # 优先使用传入的api_key，然后尝试从settings获取，最后从环境变量获取
    if not api_key:
        try:
            from ty_mem_agent.config.settings import settings
            api_key = getattr(settings, 'DIDI_API_KEY', None)
        except ImportError:
            pass
        
        if not api_key:
            api_key = os.environ.get('DIDI_API_KEY', '')
    
    if not api_key:
        raise ValueError(
            "滴滴 API Key 未配置！\n"
            "请在环境变量中设置 DIDI_API_KEY 或在调用时传入 api_key 参数\n"
            "获取 Key: 访问 https://mcp.didichuxing.com 申请"
        )
    
    # 获取模式，优先使用传入的mode，然后从settings获取，最后从环境变量获取
    if mode == "production":
        try:
            from ty_mem_agent.config.settings import settings
            mode = getattr(settings, 'DIDI_MCP_MODE', 'production')
        except ImportError:
            mode = os.environ.get('DIDI_MCP_MODE', 'production')
    
    # 根据模式选择不同的URL
    if mode == "sandbox":
        base_url = "https://mcp.didichuxing.com/mcp-servers-sandbox"
        logger.info("🔧 使用滴滴 MCP 调试模式")
    else:
        base_url = "https://mcp.didichuxing.com/mcp-servers"
        logger.info("🚀 使用滴滴 MCP 生产模式")
    
    config = {
        "mcpServers": {
            "Didi-Ride": {
                "type": "streamable-http",
                "url": f"{base_url}?key={api_key}",
                "sse_read_timeout": 300,
                "headers": {
                    "Accept": "text/event-stream",
                    "Cache-Control": "no-cache"
                }
            }
        }
    }
    
    logger.info("✅ 滴滴 MCP Server 配置已生成")
    logger.info(f"   Server URL: {base_url}")
    logger.info(f"   Connection Type: Streamable HTTP")
    logger.info(f"   Mode: {mode}")
    logger.info(f"   API Key: {api_key[:8]}...{api_key[-4:] if len(api_key) > 12 else '****'}")
    
    return config


class DidiMCPServerManager:
    """滴滴 MCP Server 管理器"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DidiMCPServerManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.mcp_manager = None
            self.tools: List[BaseTool] = []
            self.original_tools: List[BaseTool] = []  # 保存原始工具
            self._initialized = True
    
    def initialize(self, api_key: Optional[str] = None, mode: str = "production") -> None:
        """
        初始化滴滴 MCP Server 连接
        
        Args:
            api_key: 滴滴 API Key
            mode: 运行模式，"production" 或 "sandbox"
        """
        # 如果已经初始化过，不重复初始化
        if self.tools:
            logger.debug(f"✅ 滴滴 MCP Server 已初始化，跳过重复初始化")
            return
        
        try:
            from qwen_agent.tools.mcp_manager import MCPManager
        except ImportError as e:
            logger.error("❌ 无法导入 MCPManager，请安装 mcp: pip install -U mcp")
            raise ImportError("需要安装 mcp: pip install -U mcp") from e
        
        # 获取配置
        mcp_config = get_didi_mcp_server_config(api_key, mode)
        
        # 初始化 MCP Manager
        logger.info("🚀 正在连接滴滴 MCP Server...")
        self.mcp_manager = MCPManager()
        
        try:
            # 初始化配置并获取原始工具
            self.original_tools = self.mcp_manager.initConfig(mcp_config)
            
            # 使用日志包装器包装所有工具
            self.tools = [LoggingToolWrapper(tool) for tool in self.original_tools]
            
            logger.info(f"✅ 成功连接滴滴 MCP Server")
            logger.info(f"✅ 注册了 {len(self.tools)} 个 MCP 工具（已启用调用日志）")
            
            # 打印工具列表
            self._print_tools()
            
        except Exception as e:
            logger.error(f"❌ 连接滴滴 MCP Server 失败: {e}")
            logger.error("   请检查:")
            logger.error("   1. API Key 是否正确")
            logger.error("   2. 网络连接是否正常")
            logger.error("   3. 滴滴 MCP 服务是否可用")
            raise
    
    def _print_tools(self) -> None:
        """打印已注册的工具列表"""
        if not self.tools:
            logger.info("暂无已注册的工具")
            return
        
        logger.info(f"\n{'='*60}")
        logger.info("滴滴 MCP 工具列表")
        logger.info(f"{'='*60}")
        
        for i, tool in enumerate(self.tools, 1):
            logger.info(f"{i}. {tool.name}")
            if hasattr(tool, 'description') and tool.description:
                logger.info(f"   描述: {tool.description}")
        
        logger.info(f"{'='*60}\n")
    
    def get_tools(self) -> List[BaseTool]:
        """获取滴滴 MCP 工具列表"""
        if not self.tools:
            logger.warning("⚠️ 滴滴 MCP Server 未初始化，请先调用 initialize()")
            return []
        return self.tools
    
    def get_original_tools(self) -> List[BaseTool]:
        """获取原始工具列表（未包装）"""
        if not self.original_tools:
            logger.warning("⚠️ 滴滴 MCP Server 未初始化，请先调用 initialize()")
            return []
        return self.original_tools
    
    def shutdown(self) -> None:
        """关闭滴滴 MCP Server 连接"""
        if self.mcp_manager:
            try:
                self.mcp_manager.shutdown()
                logger.info("✅ 滴滴 MCP Server 已关闭")
            except Exception as e:
                logger.error(f"❌ 关闭滴滴 MCP Server 时出错: {e}")
        
        self.tools.clear()
        self.original_tools.clear()


def get_didi_mcp_manager(api_key: Optional[str] = None, mode: str = "production") -> DidiMCPServerManager:
    """
    获取滴滴 MCP Server 管理器实例
    
    Args:
        api_key: 滴滴 API Key
        mode: 运行模式，"production" 或 "sandbox"
        
    Returns:
        DidiMCPServerManager 实例
    """
    manager = DidiMCPServerManager()
    manager.initialize(api_key, mode)
    return manager


def register_didi_tools(api_key: Optional[str] = None, mode: str = "production") -> List[BaseTool]:
    """
    注册滴滴 MCP 工具（只保留打车相关功能）
    
    Args:
        api_key: 滴滴 API Key
        mode: 运行模式，"production" 或 "sandbox"
        
    Returns:
        滴滴打车工具列表
    """
    manager = get_didi_mcp_manager(api_key, mode)
    all_tools = manager.get_tools()
    
    # 只保留打车相关工具，过滤掉地图相关功能
    taxi_tools = []
    excluded_tools = []
    
    for tool in all_tools:
        tool_name = tool.name.lower()
        # 保留打车相关工具和文本搜索工具（打车需要）
        if "taxi_" in tool_name or "maps_textsearch" in tool_name:
            taxi_tools.append(tool)
        else:
            excluded_tools.append(tool.name)
    
    logger.info(f"📋 已注册 {len(taxi_tools)} 个滴滴打车工具（从 {len(all_tools)} 个总工具中筛选）")
    logger.info(f"🚫 已禁用 {len(excluded_tools)} 个地图相关工具，使用高德地图替代")
    
    for tool in taxi_tools:
        logger.debug(f"   ✅ {tool.name}: {tool.description}")
    
    for tool_name in excluded_tools:
        logger.debug(f"   🚫 {tool_name}: 已禁用，使用高德地图替代")
    
    return taxi_tools




def shutdown_didi_mcp() -> None:
    """关闭滴滴 MCP Server"""
    manager = DidiMCPServerManager()
    manager.shutdown()
