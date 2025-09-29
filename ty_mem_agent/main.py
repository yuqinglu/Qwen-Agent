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
from server.chat_server import ChatServer
from memory.memos_client import cleanup_memory_manager
from utils.logger_config import setup_logger, get_logger


class TYMemoryAgentApp:
    """TY Memory Agent 主应用程序"""
    
    def __init__(self):
        self.chat_server = None
        self.running = False
        
        # 配置日志
        self._setup_logging()
    
    def _setup_logging(self):
        """配置日志系统"""
        # 使用统一的日志配置
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
    
    def _display_config(self):
        """显示配置信息"""
        self.logger.info("=" * 50)
        self.logger.info("📋 TY Memory Agent 配置信息")
        self.logger.info("=" * 50)
        self.logger.info(f"🌐 服务地址: http://{settings.HOST}:{settings.PORT}")
        self.logger.info(f"🤖 LLM模型: {settings.DEFAULT_LLM_MODEL}")
        self.logger.info(f"🧠 记忆系统: {settings.MEMOS_API_BASE}")
        self.logger.info(f"🔧 MCP服务: {len([s for s in settings.MCP_SERVICES.values() if s.get('enabled')])} 个已启用")
        self.logger.info(f"📊 调试模式: {'开启' if settings.DEBUG else '关闭'}")
        self.logger.info(f"📝 日志级别: {settings.LOG_LEVEL}")
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
            await cleanup_memory_manager()
            self.logger.info("✅ 记忆系统已清理")
            
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
