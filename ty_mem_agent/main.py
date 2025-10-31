#!/usr/bin/env python3
"""
TY Memory Agent 主程序
启动智能记忆助手系统
"""

import asyncio
import sys
import signal
from pathlib import Path

# 添加项目路径
sys.path.append(str(Path(__file__).parent.parent))

from config.settings import settings, validate_configuration
from utils.logger_config import setup_logger, get_logger

# 延迟导入，避免 MCPManager 在 main 初始化前被创建
# from server.chat_server import ChatServer
# from memory.memos_client import cleanup_memory_manager
# from mcp import get_amap_mcp_manager, shutdown_amap_mcp


class TYMemoryAgentApp:
    """TY Memory Agent 主应用程序"""
    
    def __init__(self):
        self.chat_server = None
        self.running = False
        
        # 配置日志
        self._setup_logging()
    
    def _setup_logging(self):
        """配置日志系统"""
        setup_logger(
            name="TYMemoryAgent",
            level=settings.LOG_LEVEL,
            log_file=settings.LOG_FILE,
            rotation="10 MB",
            retention="7 days"
        )
        
        # 获取logger实例
        self.logger = get_logger("MainApp")
        self.logger.info("📋 日志系统初始化完成")
    
    async def initialize(self):
        """初始化应用"""
        try:
            self.logger.info("🚀 初始化 TY Memory Agent...")
            
            # 验证配置
            validate_configuration()
            self.logger.info("✅ 配置验证通过")
            
            # 显示配置信息
            self._display_config()
            
            # 预初始化 MCP 服务
            await self._initialize_mcp_services()
            
            # 延迟导入 ChatServer
            from server.chat_server import ChatServer
            
            # 初始化聊天服务器
            self.chat_server = ChatServer()
            self.logger.info("✅ 聊天服务器初始化完成")
            
            # 设置信号处理
            self._setup_signal_handlers()
            
            self.logger.info("🎉 TY Memory Agent 初始化完成！")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 初始化失败: {e}")
            return False
    
    async def _initialize_mcp_services(self):
        """初始化所有工具（使用统一的工具注册中心）"""
        self.logger.info("")
        self.logger.info("=" * 50)
        self.logger.info("🔧 初始化工具注册中心...")
        self.logger.info("=" * 50)
        
        # 使用统一的工具注册中心
        from ty_mem_agent.mcp_integrations import initialize_tools, get_tool_registry
        
        # 初始化工具注册中心
        await initialize_tools()
        
        # 验证初始化是否成功
        registry = get_tool_registry()
        if registry._initialized and registry.tools_cache:
            total_tools = sum(len(tools) for tools in registry.tools_cache.values())
            self.logger.info(f"✅ 工具注册中心初始化成功，共加载 {total_tools} 个工具")
        else:
            self.logger.warning("⚠️ 工具注册中心初始化后未获取到工具，Agent 将在无工具模式下运行")
        
        self.logger.info("=" * 50)
    
    async def _initialize_amap_mcp(self):
        """[已废弃] 初始化高德地图 MCP Server - 现在由 ToolRegistry 统一管理"""
        return  # 已废弃，直接返回
        
        # 以下代码保留供参考
        try:
            # 延迟导入项目 MCP 集成模块
            from ty_mem_agent.mcp_integrations import get_amap_mcp_manager
            
            self.logger.info("📍 正在连接高德地图 MCP Server...")
            
            # 检查 API Key
            amap_token = settings.AMAP_TOKEN if hasattr(settings, 'AMAP_TOKEN') else None
            if not amap_token:
                self.logger.warning("⚠️  未配置 AMAP_TOKEN，跳过高德 MCP 初始化")
                self.logger.warning("   如需使用高德地图功能，请在 .env 中设置 AMAP_TOKEN")
                return
            
            # 获取 MCP Manager 单例
            manager = get_amap_mcp_manager()
            
            # 初始化连接
            manager.initialize(api_key=amap_token, mode="sse")
            
            # 获取工具列表
            tools = manager.get_tools()
            
            if tools:
                self.logger.info(f"✅ 高德 MCP Server 连接成功")
                self.logger.info(f"✅ 已注册 {len(tools)} 个工具（已启用调用日志）")
                
                # 打印工具列表
                self.logger.info("📋 可用工具列表:")
                for i, tool in enumerate(tools, 1):
                    tool_name = getattr(tool, 'name', 'unknown')
                    # 获取原始工具的描述
                    if hasattr(tool, 'original_tool'):
                        desc = getattr(tool.original_tool, 'description', '')
                    else:
                        desc = getattr(tool, 'description', '')
                    
                    # 简化描述
                    if desc and len(desc) > 50:
                        desc = desc[:50] + "..."
                    
                    self.logger.info(f"   {i:2d}. {tool_name}")
                    if desc:
                        self.logger.debug(f"       {desc}")
            else:
                self.logger.warning("⚠️  高德 MCP Server 连接成功，但未获取到工具")
                
        except ImportError as e:
            self.logger.error(f"❌ 无法导入 MCP 模块: {e}")
            self.logger.error("   请运行: pip install -U mcp")
        except Exception as e:
            self.logger.error(f"❌ 高德 MCP Server 连接失败: {e}")
            self.logger.error("   请检查:")
            self.logger.error("   1. AMAP_TOKEN 是否正确")
            self.logger.error("   2. 网络连接是否正常")
            self.logger.error("   3. MCP 版本是否符合要求 (pip install -U mcp)")
    
    async def _initialize_time_mcp(self):
        """[已废弃] 初始化时间查询 MCP Server - 现在由 ToolRegistry 统一管理"""
        return  # 已废弃，直接返回
        
        # 以下代码保留供参考
        try:
            # 延迟导入项目 MCP 集成模块
            from ty_mem_agent.mcp_integrations import get_time_mcp_manager
            
            self.logger.info("🕐 正在连接时间查询 MCP Server...")
            
            # 获取时间 MCP Manager 单例
            manager = get_time_mcp_manager()
            
            # 初始化连接
            manager.initialize(mode="stdio")  # 尝试使用标准 MCP Server
            
            # 获取工具列表
            tools = manager.get_tools()
            
            if tools:
                self.logger.info(f"✅ 时间查询 MCP Server 连接成功")
                self.logger.info(f"✅ 已注册 {len(tools)} 个时间工具")
                
                # 打印工具列表
                self.logger.info("📋 可用时间工具列表:")
                for i, tool in enumerate(tools, 1):
                    tool_name = getattr(tool, 'name', 'unknown')
                    desc = getattr(tool, 'description', '')
                    
                    # 简化描述
                    if desc and len(desc) > 50:
                        desc = desc[:50] + "..."
                    
                    self.logger.info(f"   {i:2d}. {tool_name}")
                    if desc:
                        self.logger.debug(f"       {desc}")
            else:
                self.logger.warning("⚠️ 时间查询 MCP Server 连接成功，但未获取到工具")
                
        except ImportError as e:
            self.logger.error(f"❌ 无法导入时间 MCP 模块: {e}")
            self.logger.error("   请运行: pip install -U mcp")
        except Exception as e:
            self.logger.error(f"❌ 时间查询 MCP Server 连接失败: {e}")
            self.logger.error("   将使用自定义时间查询工具作为备选方案")
    
    def _display_config(self):
        """显示配置信息"""
        self.logger.debug("测试debug日志")
        self.logger.info("=" * 50)
        self.logger.info("📋 TY Memory Agent 配置信息")
        self.logger.info("=" * 50)
        self.logger.info(f"🌐 服务地址: http://{settings.HOST}:{settings.PORT}")
        self.logger.info(f"🤖 LLM模型: {settings.DEFAULT_LLM_MODEL}")
        self.logger.info(f"🧠 记忆系统: {settings.MEMOS_API_BASE}")
        self.logger.info(f"🔧 MCP服务: {len([s for s in settings.MCP_SERVICES.values() if s.get('enabled')])} 个已启用")
        self.logger.info(f"📊 调试模式: {'开启' if settings.DEBUG else '关闭'}")
        self.logger.info(f"📝 日志级别: {settings.LOG_LEVEL}")
        
        # 打印API key信息（用于调试）
        self.logger.info("=" * 50)
        self.logger.info("🔑 API Key 配置信息")
        self.logger.info("=" * 50)
        self.logger.info(f"DASHSCOPE_API_KEY: {settings.DASHSCOPE_API_KEY[:10] if settings.DASHSCOPE_API_KEY else 'None'}...")
        self.logger.info(f"OPENAI_API_KEY: {settings.OPENAI_API_KEY[:10] if settings.OPENAI_API_KEY else 'None'}...")
        self.logger.info(f"MEMOS_API_KEY: {settings.MEMOS_API_KEY[:10] if settings.MEMOS_API_KEY else 'None'}...")
        self.logger.info(f"AMAP_TOKEN: {settings.AMAP_TOKEN[:10] if settings.AMAP_TOKEN else 'None'}...")
        self.logger.info("=" * 50)
    
    def _setup_signal_handlers(self):
        """设置信号处理器"""
        def signal_handler(signum, frame):
            self.logger.info(f"📡 收到信号 {signum}，开始优雅关闭...")
            asyncio.create_task(self.shutdown())
        
        # 注册信号处理器
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def run(self):
        """运行应用"""
        if not await self.initialize():
            return False
        
        try:
            self.running = True
            self.logger.info("🚀 TY Memory Agent 启动中...")
            
            # 启动聊天服务器
            await self.chat_server.start_server()
            
        except Exception as e:
            self.logger.error(f"❌ 运行错误: {e}")
            return False
        finally:
            await self.shutdown()
        
        return True
    
    async def shutdown(self):
        """关闭应用"""
        if not self.running:
            return
        
        self.running = False
        self.logger.info("🛑 正在关闭 TY Memory Agent...")
        
        try:
            # 关闭聊天服务器
            if self.chat_server:
                await self.chat_server.cleanup()
                self.logger.info("✅ 聊天服务器已关闭")
            
            # 清理记忆管理器
            try:
                from memory.memos_client import cleanup_memory_manager
                await cleanup_memory_manager()
                self.logger.info("✅ 记忆系统已清理")
            except Exception as e:
                self.logger.warning(f"⚠️ 记忆系统清理失败: {e}")
            
            # 关闭工具注册中心（统一管理所有工具的清理）
            try:
                from ty_mem_agent.mcp_integrations import shutdown_tools
                await shutdown_tools()
                self.logger.info("✅ 工具注册中心已关闭")
            except Exception as tool_e:
                self.logger.warning(f"⚠️ 关闭工具注册中心时出错: {tool_e}")
            
            self.logger.info("👋 TY Memory Agent 已安全关闭")
            
        except Exception as e:
            self.logger.error(f"❌ 关闭时出错: {e}")


async def main():
    """主函数"""
    app = TYMemoryAgentApp()
    
    try:
        success = await app.run()
        return 0 if success else 1
    except KeyboardInterrupt:
        app.logger.info("👋 用户中断，退出程序")
        return 0
    except Exception as e:
        app.logger.error(f"❌ 程序异常退出: {e}")
        return 1


if __name__ == "__main__":
    # 运行主程序
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
