#!/usr/bin/env python3
"""
工具注册中心
统一管理所有工具的初始化、连接测试和注册
避免在多处重复配置
"""

from typing import List, Dict, Any, Optional, Union
from loguru import logger
from qwen_agent.tools.base import BaseTool

from ty_mem_agent.config.settings import settings


class ToolRegistry:
    """工具注册中心 - 单例模式"""
    
    _instance: Optional['ToolRegistry'] = None
    _initialized: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.tools_cache: Dict[str, List[BaseTool]] = {}
            self.connection_status: Dict[str, bool] = {}
            ToolRegistry._initialized = True
    
    async def initialize_all(self):
        """初始化所有工具（在应用启动时调用）"""
        logger.info("🔧 开始初始化工具注册中心...")
        
        # 初始化顺序：先测试连接，再缓存工具
        await self._init_didi_tools()
        await self._init_amap_tools()
        await self._init_bocha_search_tools()
        await self._init_variflight_tools()
        await self._init_railway_12306_tools()
        await self._init_stock_tools()
        await self._init_natural_time_tools()
        await self._init_todo_extractor_tool()
        await self._init_calendar_tools()
        await self._init_profile_tools()
        await self._init_eleme_tools()
        await self._init_feishu_meeting_tools()
        
        # 统计
        total_tools = sum(len(tools) for tools in self.tools_cache.values())
        logger.info(f"✅ 工具注册中心初始化完成，共 {total_tools} 个工具")
        self._print_tool_summary()
    
    async def _init_didi_tools(self):
        """初始化滴滴叫车工具"""
        try:
            from ty_mem_agent.mcp_integrations.didi_mcp_server import get_didi_mcp_manager
            
            logger.info("🚗 正在初始化滴滴叫车工具...")
            
            # 检查配置
            didi_api_key = getattr(settings, 'DIDI_API_KEY', None)
            didi_mode = getattr(settings, 'DIDI_MCP_MODE', 'production')
            
            if not didi_api_key:
                logger.warning("⚠️  未配置 DIDI_API_KEY，跳过滴滴工具")
                self.connection_status["didi"] = False
                self.tools_cache["didi"] = []
                return
            
            # 使用优化后的工具注册函数（只保留打车相关功能）
            from ty_mem_agent.mcp_integrations.didi_mcp_server import register_didi_tools
            tools = register_didi_tools(api_key=didi_api_key, mode=didi_mode)
            
            if tools:
                self.tools_cache["didi"] = tools
                self.connection_status["didi"] = True
                logger.info(f"✅ 滴滴叫车工具初始化成功，共 {len(tools)} 个工具")
            else:
                self.connection_status["didi"] = False
                self.tools_cache["didi"] = []
                logger.warning("⚠️  滴滴 MCP 连接成功，但未获取到工具")
                
        except Exception as e:
            logger.warning(f"⚠️  滴滴叫车工具初始化失败: {e}")
            self.connection_status["didi"] = False
            self.tools_cache["didi"] = []
    
    async def _init_amap_tools(self):
        """初始化高德地图工具"""
        try:
            from ty_mem_agent.mcp_integrations import get_amap_mcp_manager
            
            logger.info("📍 正在初始化高德地图工具...")
            
            # 检查配置
            amap_token = getattr(settings, 'AMAP_TOKEN', None)
            if not amap_token:
                logger.warning("⚠️  未配置 AMAP_TOKEN，跳过高德工具")
                self.connection_status['amap'] = False
                self.tools_cache['amap'] = []
                return
            
            # 初始化 MCP Manager
            manager = get_amap_mcp_manager()
            manager.initialize(api_key=amap_token, mode="sse")
            
            # 获取工具
            tools = manager.get_tools()
            
            if tools:
                self.tools_cache['amap'] = tools
                self.connection_status['amap'] = True
                logger.info(f"✅ 高德地图工具初始化成功，共 {len(tools)} 个工具")
            else:
                self.connection_status['amap'] = False
                self.tools_cache['amap'] = []
                logger.warning("⚠️  高德地图 MCP 连接成功，但未获取到工具")
                
        except Exception as e:
            logger.warning(f"⚠️  高德地图工具初始化失败: {e}")
            self.connection_status['amap'] = False
            self.tools_cache['amap'] = []
    
    async def _init_time_tools(self):
        """初始化时间查询工具"""
        try:
            from ty_mem_agent.mcp_integrations import get_time_mcp_manager
            
            logger.info("🕐 正在初始化时间查询工具...")
            
            # 初始化时间 MCP Manager
            manager = get_time_mcp_manager()
            manager.initialize(mode="stdio")
            
            # 获取工具
            tools = manager.get_tools()
            
            if tools:
                self.tools_cache['time'] = tools
                self.connection_status['time'] = True
                logger.info(f"✅ 时间查询工具初始化成功，共 {len(tools)} 个工具")
            else:
                self.connection_status['time'] = False
                self.tools_cache['time'] = []
                logger.warning("⚠️  时间查询工具初始化失败，将使用自定义时间工具")
                
        except Exception as e:
            logger.warning(f"⚠️  时间查询工具初始化失败: {e}")
            self.connection_status['time'] = False
            self.tools_cache['time'] = []
    
    async def _init_bocha_search_tools(self):
        """初始化博查搜索工具（只注册Web搜索，节省费用）"""
        try:
            from ty_mem_agent.mcp_integrations import get_bocha_search_mcp_manager
            
            logger.info("🔍 正在初始化博查搜索工具...")
            
            # 检查配置
            bocha_api_key = getattr(settings, 'BOCHA_API_KEY', None)
            print(f"bocha_api_key: {bocha_api_key}")
            if not bocha_api_key:
                logger.warning("⚠️  未配置 BOCHA_API_KEY，跳过博查搜索工具")
                self.connection_status['bocha_search'] = False
                self.tools_cache['bocha_search'] = []
                return
            
            # 初始化博查搜索 MCP Manager
            manager = get_bocha_search_mcp_manager()
            manager.initialize(api_key=bocha_api_key)
            
            # 只获取Web搜索工具（节省费用）
            web_search_tool = manager.get_web_search_tool()
            
            if web_search_tool:
                self.tools_cache['bocha_search'] = [web_search_tool]
                self.connection_status['bocha_search'] = True
                logger.info(f"✅ 博查Web搜索工具初始化成功")
                logger.info(f"   💡 只注册Web搜索，不注册AI搜索（节省费用）")
            else:
                self.connection_status['bocha_search'] = False
                self.tools_cache['bocha_search'] = []
                logger.warning("⚠️  未找到Web搜索工具")
                
        except Exception as e:
            logger.warning(f"⚠️  博查搜索工具初始化失败: {e}")
            self.connection_status['bocha_search'] = False
            self.tools_cache['bocha_search'] = []
    
    async def _init_variflight_tools(self):
        """初始化飞常准航班信息查询工具"""
        try:
            from ty_mem_agent.mcp_integrations import get_variflight_mcp_manager
            
            logger.info("✈️  正在初始化飞常准航班信息查询工具...")
            
            # 检查配置
            variflight_api_key = getattr(settings, 'VARIFLIGHT_API_KEY', None)
            if not variflight_api_key:
                logger.warning("⚠️  未配置 VARIFLIGHT_API_KEY，跳过飞常准工具")
                self.connection_status['variflight'] = False
                self.tools_cache['variflight'] = []
                return
            
            manager = get_variflight_mcp_manager()
            manager.initialize(api_key=variflight_api_key)
            
            # 只获取航班核心工具（避免与其他工具混淆）
            tools = manager.get_flight_tools_only()
            
            if tools:
                self.tools_cache['variflight'] = tools
                self.connection_status['variflight'] = True
                logger.info(f"✅ 飞常准工具初始化成功，共 {len(tools)} 个工具")
            else:
                self.connection_status['variflight'] = False
                self.tools_cache['variflight'] = []
                logger.warning("⚠️  未找到飞常准工具")
                
        except Exception as e:
            logger.warning(f"⚠️  飞常准工具初始化失败: {e}")
            self.connection_status['variflight'] = False
            self.tools_cache['variflight'] = []
    
    async def _init_railway_12306_tools(self):
        """初始化12306铁路票务查询工具"""
        try:
            from ty_mem_agent.mcp_integrations import get_railway_12306_mcp_manager
            
            logger.info("🚄 正在初始化12306铁路票务查询工具...")
            
            # 初始化12306 MCP Manager
            manager = get_railway_12306_mcp_manager()
            manager.initialize()
            
            # 获取工具
            tools = manager.get_tools()
            
            if tools:
                self.tools_cache['railway_12306'] = tools
                self.connection_status['railway_12306'] = True
                logger.info(f"✅ 12306工具初始化成功，共 {len(tools)} 个工具")
            else:
                self.connection_status['railway_12306'] = False
                self.tools_cache['railway_12306'] = []
                logger.warning("⚠️  12306工具初始化失败")
                
        except Exception as e:
            logger.warning(f"⚠️  12306工具初始化失败: {e}")
            self.connection_status['railway_12306'] = False
            self.tools_cache['railway_12306'] = []
    
    async def _init_stock_tools(self):
        """初始化股票查询工具"""
        try:
            from ty_mem_agent.mcp_integrations import get_stock_mcp_manager
            
            logger.info("📈 正在初始化股票查询工具...")
            
            # 检查配置
            dashscope_api_key = getattr(settings, 'DASHSCOPE_API_KEY', None)
            if not dashscope_api_key:
                logger.warning("⚠️  未配置 DASHSCOPE_API_KEY，跳过股票查询工具")
                self.connection_status['stock'] = False
                self.tools_cache['stock'] = []
                return
            
            # 初始化股票查询 MCP Manager
            manager = get_stock_mcp_manager()
            manager.initialize(api_key=dashscope_api_key)
            
            # 获取工具
            tools = manager.get_tools()
            
            if tools:
                self.tools_cache['stock'] = tools
                self.connection_status['stock'] = True
                logger.info(f"✅ 股票查询工具初始化成功，共 {len(tools)} 个工具")
            else:
                self.connection_status['stock'] = False
                self.tools_cache['stock'] = []
                logger.warning("⚠️  股票查询工具初始化失败")
                
        except Exception as e:
            logger.warning(f"⚠️  股票查询工具初始化失败: {e}")
            self.connection_status['stock'] = False
            self.tools_cache['stock'] = []
    
    async def _init_natural_time_tools(self):
        """初始化自然语言时间解析工具"""
        try:
            from ty_mem_agent.tools.natural_time_parser import NaturalTimeParserTool
            
            logger.info("🕐 正在初始化自然语言时间解析工具...")
            
            # 创建自然语言时间解析工具
            tools = [NaturalTimeParserTool()]
            
            self.tools_cache['natural_time'] = tools
            self.connection_status['natural_time'] = True
            logger.info(f"✅ 自然语言时间解析工具初始化成功，共 {len(tools)} 个工具")
            
        except Exception as e:
            logger.error(f"❌ 自然语言时间解析工具初始化失败: {e}")
            self.connection_status['natural_time'] = False
            self.tools_cache['natural_time'] = []
    
    
    async def _init_todo_extractor_tool(self):
        """初始化待办信息提取工具（仅提取，不创建）"""
        try:
            from ty_mem_agent.tools.todo_tools import TodoExtractorTool
            
            logger.info("📝 正在初始化待办信息提取工具...")
            
            # 只注册提取工具，不注册查询和更新工具（使用日历MCP工具替代）
            tools = [TodoExtractorTool()]
            
            self.tools_cache['todo_extractor'] = tools
            self.connection_status['todo_extractor'] = True
            logger.info(f"✅ 待办信息提取工具初始化成功，共 {len(tools)} 个工具")
            logger.info("   💡 注意：此工具只提取信息，创建待办请使用日历MCP工具")
            
        except Exception as e:
            logger.error(f"❌ 待办信息提取工具初始化失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.connection_status['todo_extractor'] = False
            self.tools_cache['todo_extractor'] = []
    
    async def _init_calendar_tools(self):
        """初始化日历MCP工具（替代待办工具）"""
        try:
            from ty_mem_agent.mcp_integrations import get_calendar_mcp_manager
            from ty_mem_agent.mcp_integrations.calendar_tool_wrapper import wrap_calendar_tools
            
            logger.info("📅 正在初始化日历MCP工具...")
            
            # 初始化日历MCP Manager
            manager = get_calendar_mcp_manager()
            manager.initialize()
            
            # 获取原始工具
            original_tools = manager.get_tools()
            
            if original_tools:
                # 包装工具以自动处理user_id转换
                wrapped_tools = wrap_calendar_tools(original_tools)
                
                self.tools_cache['calendar'] = wrapped_tools
                self.connection_status['calendar'] = True
                logger.info(f"✅ 日历MCP工具初始化成功，共 {len(wrapped_tools)} 个工具")
                
                # 记录可用工具
                for tool in wrapped_tools:
                    logger.debug(f"   📋 工具: {tool.name}")
            else:
                self.connection_status['calendar'] = False
                self.tools_cache['calendar'] = []
                logger.warning("⚠️  日历MCP连接成功，但未获取到工具")
                
        except Exception as e:
            logger.warning(f"⚠️  日历MCP工具初始化失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.connection_status['calendar'] = False
            self.tools_cache['calendar'] = []
    
    async def _init_profile_tools(self):
        """初始化用户画像管理工具"""
        try:
            from ty_mem_agent.tools.profile_tools import (
                UpdateUserProfileTool,
                GetUserProfileTool
            )
            
            logger.info("👤 正在初始化用户画像管理工具...")
            
            # 创建用户画像工具实例
            tools = [
                UpdateUserProfileTool(),
                GetUserProfileTool()
            ]
            
            self.tools_cache['profile'] = tools
            self.connection_status['profile'] = True
            logger.info(f"✅ 用户画像管理工具初始化成功，共 {len(tools)} 个工具")
            
        except Exception as e:
            logger.error(f"❌ 用户画像管理工具初始化失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.connection_status['profile'] = False
            self.tools_cache['profile'] = []
    
    async def _init_eleme_tools(self):
        """初始化饿了么外卖工具"""
        try:
            from ty_mem_agent.tools.eleme_tools import get_eleme_tools
            
            logger.info("🍔 正在初始化饿了么外卖工具...")
            
            # 检查配置
            eleme_app_key = getattr(settings, 'ELEME_APP_KEY', None)
            eleme_app_secret = getattr(settings, 'ELEME_APP_SECRET', None)
            eleme_mode = getattr(settings, 'ELEME_MODE', 'sandbox')
            
            if not eleme_app_key or not eleme_app_secret:
                logger.warning("⚠️  未配置 ELEME_APP_KEY 或 ELEME_APP_SECRET，跳过饿了么工具")
                self.connection_status["eleme"] = False
                self.tools_cache["eleme"] = []
                return
            
            # 获取饿了么工具
            tools = get_eleme_tools(
                app_key=eleme_app_key,
                app_secret=eleme_app_secret,
                mode=eleme_mode
            )
            
            if tools:
                self.tools_cache["eleme"] = tools
                self.connection_status["eleme"] = True
                logger.info(f"✅ 饿了么外卖工具初始化成功，共 {len(tools)} 个工具")
                for tool in tools:
                    logger.debug(f"   - {tool.name}: {tool.description}")
            else:
                self.connection_status["eleme"] = False
                self.tools_cache["eleme"] = []
                logger.warning("⚠️  饿了么外卖工具初始化失败")
                
        except Exception as e:
            logger.warning(f"⚠️  饿了么外卖工具初始化失败: {e}")
            self.connection_status["eleme"] = False
            self.tools_cache["eleme"] = []
    
    async def _init_feishu_meeting_tools(self):
        """初始化飞书会议工具（使用官方 SDK）"""
        try:
            from ty_mem_agent.tools.feishu_meeting_sdk import get_feishu_meeting_sdk_tools
            
            logger.info("📅 正在初始化飞书会议工具（SDK版本）...")
            
            # 检查配置
            feishu_app_id = getattr(settings, 'FEISHU_APP_ID', None)
            feishu_app_secret = getattr(settings, 'FEISHU_APP_SECRET', None)
            
            if not feishu_app_id or not feishu_app_secret:
                logger.warning("⚠️  未配置 FEISHU_APP_ID 或 FEISHU_APP_SECRET，跳过飞书会议工具")
                self.connection_status["feishu_meeting"] = False
                self.tools_cache["feishu_meeting"] = []
                return
            
            # 获取飞书会议工具（SDK版本）
            tools = get_feishu_meeting_sdk_tools()
            
            if tools:
                self.tools_cache["feishu_meeting"] = tools
                self.connection_status["feishu_meeting"] = True
                logger.info(f"✅ 飞书会议工具（SDK版本）初始化成功，共 {len(tools)} 个工具")
                for tool in tools:
                    logger.debug(f"   - {tool.name}: {tool.description[:80]}...")
            else:
                self.connection_status["feishu_meeting"] = False
                self.tools_cache["feishu_meeting"] = []
                logger.warning("⚠️  飞书会议工具初始化失败")
                
        except Exception as e:
            logger.warning(f"⚠️  飞书会议工具初始化失败: {e}")
            self.connection_status["feishu_meeting"] = False
            self.tools_cache["feishu_meeting"] = []
    
    def get_all_tools(self) -> List[BaseTool]:
        """获取所有可用工具"""
        all_tools = []
        for category, tools in self.tools_cache.items():
            all_tools.extend(tools)
        return all_tools
    
    def get_tools_by_category(self, category: str) -> List[BaseTool]:
        """根据类别获取工具"""
        return self.tools_cache.get(category, [])
    
    def is_category_available(self, category: str) -> bool:
        """检查某个类别的工具是否可用"""
        return self.connection_status.get(category, False)
    
    def get_connection_status(self) -> Dict[str, bool]:
        """获取所有工具的连接状态"""
        return self.connection_status.copy()
    
    def _print_tool_summary(self):
        """打印工具摘要"""
        logger.info("=" * 60)
        logger.info("📋 工具注册中心摘要")
        logger.info("=" * 60)
        
        for category, status in self.connection_status.items():
            tools = self.tools_cache.get(category, [])
            status_icon = "✅" if status else "❌"
            logger.info(f"{status_icon} {category:10s}: {len(tools):2d} 个工具")
            
            # 打印工具列表
            if tools:
                for i, tool in enumerate(tools, 1):
                    tool_name = getattr(tool, 'name', 'unknown')
                    logger.debug(f"   {i:2d}. {tool_name}")
        
        logger.info("=" * 60)
    
    async def shutdown(self):
        """清理资源"""
        try:
            # 关闭 MCP 连接
            from ty_mem_agent.mcp_integrations import (
                get_amap_mcp_manager,
                get_bocha_search_mcp_manager,
                get_variflight_mcp_manager,
                get_railway_12306_mcp_manager,
                get_stock_mcp_manager
            )
            
            if self.connection_status.get('amap'):
                try:
                    manager = get_amap_mcp_manager()
                    if manager and hasattr(manager, 'shutdown'):
                        # 高德地图工具的 shutdown 是同步方法
                        manager.shutdown()
                        logger.info("✅ 高德地图工具已关闭")
                    else:
                        logger.debug("高德地图工具无需关闭或已关闭")
                except Exception as e:
                    logger.warning(f"⚠️  关闭高德地图工具失败: {e}")
            
            if self.connection_status.get('bocha_search'):
                try:
                    manager = get_bocha_search_mcp_manager()
                    if manager and hasattr(manager, 'cleanup'):
                        manager.cleanup()
                        logger.info("✅ 博查搜索工具已关闭")
                    else:
                        logger.debug("博查搜索工具无需关闭或已关闭")
                except Exception as e:
                    logger.warning(f"⚠️  关闭博查搜索工具失败: {e}")
            
            if self.connection_status.get('variflight'):
                try:
                    manager = get_variflight_mcp_manager()
                    if manager and hasattr(manager, 'cleanup'):
                        manager.cleanup()
                        logger.info("✅ 飞常准工具已关闭")
                    else:
                        logger.debug("飞常准工具无需关闭或已关闭")
                except Exception as e:
                    logger.warning(f"⚠️  关闭飞常准工具失败: {e}")
            
            if self.connection_status.get('railway_12306'):
                try:
                    manager = get_railway_12306_mcp_manager()
                    if manager and hasattr(manager, 'cleanup'):
                        manager.cleanup()
                        logger.info("✅ 12306工具已关闭")
                    else:
                        logger.debug("12306工具无需关闭或已关闭")
                except Exception as e:
                    logger.warning(f"⚠️  关闭12306工具失败: {e}")
            
            if self.connection_status.get('stock'):
                try:
                    manager = get_stock_mcp_manager()
                    if manager and hasattr(manager, 'cleanup'):
                        manager.cleanup()
                        logger.info("✅ 股票查询工具已关闭")
                    else:
                        logger.debug("股票查询工具无需关闭或已关闭")
                except Exception as e:
                    logger.warning(f"⚠️  关闭股票查询工具失败: {e}")
            
            logger.info("✅ 工具注册中心已关闭")
            
        except Exception as e:
            logger.error(f"❌ 关闭工具注册中心失败: {e}")


# 全局单例实例
_tool_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """获取工具注册中心单例"""
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
    return _tool_registry


async def initialize_tools():
    """初始化所有工具（快捷函数）"""
    registry = get_tool_registry()
    await registry.initialize_all()
    return registry


async def shutdown_tools():
    """关闭所有工具（快捷函数）"""
    registry = get_tool_registry()
    await registry.shutdown()

