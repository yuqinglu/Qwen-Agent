"""
VariFlight MCP Server 配置
飞常准航班信息查询服务
提供航班实时动态、行程价格、舒适度查询等功能
"""

import os
from typing import Dict, Optional, List
from qwen_agent.tools.base import BaseTool
from ty_mem_agent.utils.logger_config import get_logger
from ty_mem_agent.mcp_integrations.tool_wrapper import LoggingToolWrapper

logger = get_logger("VariFlightMCPServer")


def get_variflight_mcp_server_config(api_key: Optional[str] = None) -> Dict:
    """
    获取飞常准 MCP Server 配置
    
    Args:
        api_key: 飞常准 API Key，如果不提供则从环境变量 VARIFLIGHT_API_KEY 读取
        
    Returns:
        MCP Server 配置字典
    """
    api_key = api_key or os.environ.get('VARIFLIGHT_API_KEY', '')
    
    if not api_key:
        raise ValueError(
            "飞常准 API Key 未配置！\n"
            "请在环境变量中设置 VARIFLIGHT_API_KEY 或在调用时传入 api_key 参数\n"
            "获取 Key: 在飞友AI开放平台申请"
        )
    
    config = {
        "mcpServers": {
            "VariFlight-Aviation": {
                "type": "streamable-http",
                "url": f"https://ai.variflight.com/servers/aviation/mcp/?api_key={api_key}",
                "sse_read_timeout": 300
            }
        }
    }
    
    logger.info("✅ 飞常准 MCP Server 配置已生成")
    logger.info(f"   Server URL: https://ai.variflight.com/servers/aviation/mcp/")
    logger.info(f"   Connection Type: Streamable HTTP")
    logger.info(f"   API Key: {api_key[:8]}...{api_key[-4:] if len(api_key) > 12 else '****'}")
    
    return config


class VariFlightMCPServerManager:
    """飞常准 MCP Server 管理器"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(VariFlightMCPServerManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.mcp_manager = None
            self.tools: List[BaseTool] = []
            self.original_tools: List[BaseTool] = []
            self._initialized = True
    
    def initialize(self, api_key: Optional[str] = None) -> None:
        """
        初始化飞常准 MCP Server 连接
        
        Args:
            api_key: 飞常准 API Key
        """
        if self.tools:
            logger.debug("✅ 飞常准 MCP Server 已初始化，跳过重复初始化")
            return
        
        try:
            from qwen_agent.tools.mcp_manager import MCPManager
        except ImportError as e:
            logger.error("❌ 无法导入 MCPManager，请安装 mcp: pip install -U mcp")
            raise ImportError("需要安装 mcp: pip install -U mcp") from e
        
        mcp_config = get_variflight_mcp_server_config(api_key)
        
        logger.info("✈️  正在连接飞常准 MCP Server...")
        self.mcp_manager = MCPManager()
        
        try:
            self.original_tools = self.mcp_manager.initConfig(mcp_config)
            
            if self.original_tools:
                # 包装工具以添加日志记录
                self.tools = []
                for tool in self.original_tools:
                    wrapped_tool = LoggingToolWrapper(tool)
                    self.tools.append(wrapped_tool)
                
                logger.info(f"✅ 飞常准 MCP Server 连接成功，获取到 {len(self.tools)} 个工具")
                
                # 记录可用工具
                for tool in self.tools:
                    logger.info(f"   📋 工具: {tool.name} - {getattr(tool, 'description', '无描述')}")
            else:
                logger.warning("⚠️  飞常准 MCP Server 连接成功，但未获取到工具")
                
        except Exception as e:
            logger.error(f"❌ 飞常准 MCP Server 连接失败: {e}")
            raise e
    
    def get_tools(self) -> List[BaseTool]:
        """获取飞常准工具列表"""
        if not self.tools:
            self.initialize()
        return self.tools
    
    def get_flight_tools_only(self) -> List[BaseTool]:
        """
        获取航班相关工具（只返回指定的两个核心工具）
        
        保留的工具：
        1. searchFlightsByNumber - 航班实时动态查询
        2. searchFlightItineraries - 航班行程方案查询
        
        排除的工具：
        - 其他所有非核心工具
        - 避免与其他工具混淆
        """
        tools = self.get_tools()
        filtered_tools = []
        
        # 只保留指定的两个工具
        target_tools = [
            'searchflightsbynumber',      # 航班实时动态查询
            'searchflightitineraries'     # 航班行程方案查询
        ]
        
        for tool in tools:
            tool_name = getattr(tool, 'name', '').lower()
            
            # 精确匹配工具名称
            if any(target in tool_name for target in target_tools):
                filtered_tools.append(tool)
                logger.info(f"🎯 选择核心航班工具: {tool.name}")
        
        if filtered_tools:
            logger.info(f"✅ 筛选出 {len(filtered_tools)} 个核心航班工具")
            for tool in filtered_tools:
                logger.info(f"   📋 保留: {tool.name}")
        else:
            logger.warning("⚠️  未找到核心航班工具")
            if tools:
                logger.warning(f"   可用工具: {[t.name for t in tools]}")
        
        return filtered_tools
    
    def cleanup(self):
        """清理资源"""
        if self.mcp_manager:
            try:
                self.mcp_manager.shutdown()
                logger.info("✅ 飞常准 MCP Server 已关闭")
            except Exception as e:
                logger.warning(f"⚠️ 关闭飞常准 MCP Server 时出错: {e}")
        
        self.tools = []
        self.original_tools = []


# 全局实例
_variflight_manager = None


def get_variflight_mcp_manager(api_key: Optional[str] = None) -> VariFlightMCPServerManager:
    """获取飞常准 MCP Manager 实例"""
    global _variflight_manager
    if _variflight_manager is None:
        _variflight_manager = VariFlightMCPServerManager()
    return _variflight_manager


def register_variflight_tools(api_key: Optional[str] = None) -> List[BaseTool]:
    """注册飞常准工具"""
    manager = get_variflight_mcp_manager(api_key)
    manager.initialize(api_key)
    return manager.get_tools()


def register_variflight_flight_tools_only(api_key: Optional[str] = None) -> List[BaseTool]:
    """
    只注册航班核心工具（推荐）
    
    保留的工具：
    1. searchFlightsByNumber - 航班实时动态查询
    2. searchFlightItineraries - 航班行程方案查询
    
    排除的工具：
    - searchFlightsByDepArr - 按起降地查询
    - getFlightTransferInfo - 中转信息
    - getRealtimeLocationByAnum - 实时位置
    - getTodayDate - 今日日期
    - list_resources - 资源列表
    - read_resource - 读取资源
    
    原因：
    1. 避免与其他工具混淆
    2. 专注于核心航班功能
    3. 减少不必要的工具调用
    """
    manager = get_variflight_mcp_manager(api_key)
    manager.initialize(api_key)
    return manager.get_flight_tools_only()


def shutdown_variflight_mcp():
    """关闭飞常准 MCP 连接"""
    global _variflight_manager
    if _variflight_manager:
        _variflight_manager.cleanup()
        _variflight_manager = None
        logger.info("✅ 飞常准 MCP 连接已关闭")


if __name__ == "__main__":
    # 测试配置
    try:
        config = get_variflight_mcp_server_config()
        print("✅ 飞常准 MCP 配置测试通过")
        print(f"配置: {config}")
    except Exception as e:
        print(f"❌ 配置测试失败: {e}")

