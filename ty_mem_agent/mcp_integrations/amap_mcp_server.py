"""
高德地图 MCP Server 配置
基于标准 MCP 协议连接高德官方 MCP Server
参考文档: https://lbs.amap.com/api/mcp-server/gettingstarted
"""

import os
from typing import Dict, Optional, List
from qwen_agent.tools.base import BaseTool
from ty_mem_agent.utils.logger_config import get_logger

logger = get_logger("AmapMCPServer")


def get_amap_mcp_server_config(api_key: Optional[str] = None) -> Dict:
    """
    获取高德地图 MCP Server 配置
    
    Args:
        api_key: 高德地图 API Key，如果不提供则从环境变量 AMAP_TOKEN 读取
        
    Returns:
        MCP Server 配置字典，用于 QwenAgent MCPManager
        
    Example:
        >>> config = get_amap_mcp_server_config()
        >>> # 配置格式：
        >>> # {
        >>> #     "mcpServers": {
        >>> #         "amap_maps": {
        >>> #             "url": "https://mcp.amap.com/sse?key=YOUR_KEY"
        >>> #         }
        >>> #     }
        >>> # }
    """
    api_key = api_key or os.environ.get('AMAP_TOKEN', '')
    
    if not api_key:
        raise ValueError(
            "高德地图 API Key 未配置！\n"
            "请在环境变量中设置 AMAP_TOKEN 或在调用时传入 api_key 参数\n"
            "获取 Key: https://lbs.amap.com/api/webservice/guide/create-project/get-key"
        )
    
    # 根据高德官方文档和 QwenAgent MCPManager 的要求配置
    # 必须包含外层的 "mcpServers" 键
    config = {
        "mcpServers": {
            "amap_maps": {
                "url": f"https://mcp.amap.com/sse?key={api_key}"
            }
        }
    }
    
    logger.info("✅ 高德地图 MCP Server 配置已生成")
    logger.info(f"   Server URL: https://mcp.amap.com/sse")
    
    return config


def get_amap_mcp_server_config_stdio(api_key: Optional[str] = None) -> Dict:
    """
    获取高德地图 MCP Server 配置（Node.js I/O 模式）
    
    Args:
        api_key: 高德地图 API Key
        
    Returns:
        MCP Server 配置字典（Stdio模式）
        
    Note:
        需要先安装 Node.js 和 @amap/amap-maps-mcp-server:
        npm install -g @amap/amap-maps-mcp-server
    """
    api_key = api_key or os.environ.get('AMAP_TOKEN', '')
    
    if not api_key:
        raise ValueError("高德地图 API Key 未配置！")
    
    # 根据高德官方文档和 QwenAgent MCPManager 的要求配置
    # 必须包含外层的 "mcpServers" 键
    config = {
        "mcpServers": {
            "amap_maps": {
                "command": "npx",
                "args": ["-y", "@amap/amap-maps-mcp-server"],
                "env": {
                    "AMAP_MAPS_API_KEY": api_key
                }
            }
        }
    }
    
    logger.info("✅ 高德地图 MCP Server 配置已生成 (Stdio模式)")
    logger.info("   需要 Node.js v22.14.0+ 和 @amap/amap-maps-mcp-server")
    
    return config


class LoggingToolWrapper(BaseTool):
    """工具包装器，用于添加日志记录和智能降级"""
    
    def __init__(self, original_tool: BaseTool):
        self.original_tool = original_tool
        self.name = original_tool.name
        self.description = getattr(original_tool, 'description', '')
        self.parameters = getattr(original_tool, 'parameters', {})
    
    def _generate_fallback_cities(self, original_city: str) -> list:
        """
        生成降级城市列表
        例如："重庆市渝中区" -> ["重庆市", "渝中区", "重庆"]
        """
        import re
        
        fallback_cities = []
        city = original_city.strip()
        
        # 策略1: 移除区县，保留城市
        # "重庆市渝中区" -> "重庆市"
        # "北京市朝阳区" -> "北京市"
        match = re.match(r'(.*?[市州盟])(.+[区县市])?', city)
        if match and match.group(1):
            city_only = match.group(1)
            if city_only != city:
                fallback_cities.append(city_only)
        
        # 策略2: 只保留区县
        # "重庆市渝中区" -> "渝中区"
        match = re.search(r'([^市州盟]+[区县市])$', city)
        if match:
            district_only = match.group(1)
            if district_only != city:
                fallback_cities.append(district_only)
        
        # 策略3: 移除"市"后缀
        # "重庆市" -> "重庆"
        if city.endswith('市'):
            city_without_suffix = city[:-1]
            if city_without_suffix not in fallback_cities:
                fallback_cities.append(city_without_suffix)
        
        # 去重并保持顺序
        seen = set()
        unique_cities = []
        for c in fallback_cities:
            if c and c not in seen and c != original_city:
                seen.add(c)
                unique_cities.append(c)
        
        return unique_cities
    
    def call(self, params, **kwargs):
        """带日志的工具调用"""
        import json
        
        # 解析参数
        if isinstance(params, str):
            try:
                params_dict = json.loads(params)
            except:
                params_dict = {'params': params}
        else:
            params_dict = params
        
        # 记录调用开始
        logger.info("=" * 80)
        logger.info(f"🔧 MCP 工具调用: {self.name}")
        logger.info("-" * 80)
        logger.info(f"📥 输入参数:")
        logger.info(json.dumps(params_dict, ensure_ascii=False, indent=2))
        logger.info("-" * 80)
        
        try:
            # 调用原始工具
            result = self.original_tool.call(params, **kwargs)
            
            # 特殊处理：天气工具的智能降级
            if 'weather' in self.name.lower():
                result_dict = json.loads(result) if isinstance(result, str) else result
                
                # 检查返回是否为空
                if not result_dict.get('city') or not result_dict.get('forecasts'):
                    logger.warning(f"⚠️ 天气查询返回空数据，尝试智能降级...")
                    
                    # 尝试降级策略
                    if 'city' in params_dict:
                        original_city = params_dict['city']
                        fallback_cities = self._generate_fallback_cities(original_city)
                        
                        for i, fallback_city in enumerate(fallback_cities, 1):
                            logger.info(f"🔄 降级尝试 {i}/{len(fallback_cities)}: {fallback_city}")
                            try:
                                fallback_params = params_dict.copy()
                                fallback_params['city'] = fallback_city
                                result = self.original_tool.call(json.dumps(fallback_params), **kwargs)
                                result_dict = json.loads(result) if isinstance(result, str) else result
                                
                                if result_dict.get('city') and result_dict.get('forecasts'):
                                    logger.info(f"✅ 降级成功！使用 '{fallback_city}' 查询到数据")
                                    break
                            except Exception as e:
                                logger.debug(f"降级尝试失败: {e}")
                                continue
            
            # 记录返回结果
            logger.info(f"📤 返回结果:")
            try:
                # 尝试格式化 JSON
                result_dict = json.loads(result) if isinstance(result, str) else result
                logger.info(json.dumps(result_dict, ensure_ascii=False, indent=2))
            except:
                # 如果不是 JSON，直接输出
                result_str = str(result)
                if len(result_str) > 500:
                    logger.info(f"{result_str[:500]}... (共 {len(result_str)} 字符)")
                else:
                    logger.info(result_str)
            
            logger.info("-" * 80)
            logger.info(f"✅ 工具调用成功: {self.name}")
            logger.info("=" * 80 + "\n")
            
            return result
            
        except Exception as e:
            # 记录错误
            logger.error(f"❌ 工具调用失败: {self.name}")
            logger.error(f"错误信息: {str(e)}")
            logger.info("=" * 80 + "\n")
            raise


class AmapMCPServerManager:
    """高德地图 MCP Server 管理器"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AmapMCPServerManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.mcp_manager = None
            self.tools: List[BaseTool] = []
            self.original_tools: List[BaseTool] = []  # 保存原始工具
            self._initialized = True
    
    def initialize(self, api_key: Optional[str] = None, mode: str = "sse") -> None:
        """
        初始化高德 MCP Server 连接
        
        Args:
            api_key: 高德 API Key
            mode: 连接模式，"sse" 或 "stdio"，默认 "sse"
        """
        # 如果已经初始化过，不重复初始化
        if self.tools:
            logger.debug(f"✅ 高德 MCP Server 已初始化，跳过重复初始化")
            return
        
        try:
            from qwen_agent.tools.mcp_manager import MCPManager
        except ImportError as e:
            logger.error("❌ 无法导入 MCPManager，请安装 mcp: pip install -U mcp")
            raise ImportError("需要安装 mcp: pip install -U mcp") from e
        
        # 获取配置
        if mode == "sse":
            mcp_config = get_amap_mcp_server_config(api_key)
        elif mode == "stdio":
            mcp_config = get_amap_mcp_server_config_stdio(api_key)
        else:
            raise ValueError(f"不支持的模式: {mode}，请使用 'sse' 或 'stdio'")
        
        # 初始化 MCP Manager
        logger.info("🚀 正在连接高德地图 MCP Server...")
        self.mcp_manager = MCPManager()
        
        try:
            # 初始化配置并获取原始工具
            self.original_tools = self.mcp_manager.initConfig(mcp_config)
            
            # 使用日志包装器包装所有工具
            self.tools = [LoggingToolWrapper(tool) for tool in self.original_tools]
            
            logger.info(f"✅ 成功连接高德地图 MCP Server")
            logger.info(f"✅ 注册了 {len(self.tools)} 个 MCP 工具（已启用调用日志）")
            
            # 打印工具列表
            self._print_tools()
            
        except Exception as e:
            logger.error(f"❌ 连接高德 MCP Server 失败: {e}")
            logger.error("   请检查:")
            logger.error("   1. API Key 是否正确")
            logger.error("   2. 网络连接是否正常")
            logger.error("   3. 如果使用 stdio 模式，是否已安装 Node.js 和 @amap/amap-maps-mcp-server")
            raise
    
    def _print_tools(self) -> None:
        """打印已注册的工具列表"""
        if not self.tools:
            logger.info("暂无已注册的工具")
            return
        
        logger.info(f"\n{'='*60}")
        logger.info("高德地图 MCP 工具列表")
        logger.info(f"{'='*60}")
        
        for i, tool in enumerate(self.tools, 1):
            logger.info(f"{i}. {tool.name}")
            if hasattr(tool, 'description') and tool.description:
                logger.info(f"   描述: {tool.description}")
        
        logger.info(f"{'='*60}\n")
    
    def get_tools(self) -> List[BaseTool]:
        """获取所有已注册的 MCP 工具"""
        return self.tools
    
    def shutdown(self) -> None:
        """关闭 MCP 连接"""
        if self.mcp_manager:
            try:
                self.mcp_manager.shutdown()
                logger.info("✅ 高德 MCP Server 连接已关闭")
            except Exception as e:
                logger.warning(f"⚠️ 关闭 MCP 连接时出错: {e}")


# 全局单例实例
_manager = AmapMCPServerManager()


def get_amap_mcp_manager() -> AmapMCPServerManager:
    """获取高德 MCP Server 管理器单例"""
    return _manager


def register_amap_mcp_tools(api_key: Optional[str] = None, mode: str = "sse") -> List[BaseTool]:
    """
    便捷函数：连接高德 MCP Server 并返回所有工具
    
    Args:
        api_key: 高德 API Key
        mode: 连接模式，"sse" 或 "stdio"，默认 "sse"
        
    Returns:
        所有 MCP 工具实例列表
        
    Example:
        >>> # SSE 模式（推荐）
        >>> tools = register_amap_mcp_tools()
        >>> 
        >>> # Stdio 模式（需要 Node.js）
        >>> tools = register_amap_mcp_tools(mode="stdio")
    """
    manager = get_amap_mcp_manager()
    
    if not manager.tools:
        manager.initialize(api_key, mode)
    
    return manager.get_tools()


def shutdown_amap_mcp() -> None:
    """
    关闭高德 MCP Server 连接
    
    在应用退出时调用，确保资源正确释放
    """
    manager = get_amap_mcp_manager()
    manager.shutdown()


# 便捷导出
__all__ = [
    'AmapMCPServerManager',
    'get_amap_mcp_server_config',
    'get_amap_mcp_server_config_stdio',
    'get_amap_mcp_manager',
    'register_amap_mcp_tools',
    'shutdown_amap_mcp',
]


if __name__ == "__main__":
    """测试高德 MCP Server 连接"""
    import sys
    from ty_mem_agent.utils.logger_config import init_default_logging
    
    init_default_logging()
    
    # 检查 API Key
    api_key = os.environ.get('AMAP_TOKEN')
    if not api_key:
        logger.error("❌ 请设置环境变量 AMAP_TOKEN")
        logger.info("   export AMAP_TOKEN='your_api_key'")
        sys.exit(1)
    
    # 测试 SSE 模式
    logger.info("\n" + "="*60)
    logger.info("测试高德地图 MCP Server (SSE 模式)")
    logger.info("="*60)
    
    try:
        tools = register_amap_mcp_tools(mode="sse")
        
        if tools:
            logger.info(f"\n✅ 成功！获得 {len(tools)} 个工具")
            logger.info("\n可以在 TYMemoryAgent 中使用这些工具了！")
        else:
            logger.warning("\n⚠️ 未获取到任何工具")
            
    except Exception as e:
        logger.error(f"\n❌ 测试失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        # 清理连接
        shutdown_amap_mcp()

