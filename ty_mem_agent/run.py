#!/usr/bin/env python3
"""
TY Memory Agent 快速启动脚本
"""

import os
import sys
import asyncio
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 初始化日志系统
try:
    from utils.logger_config import setup_logger, get_logger
except ImportError:
    # 如果在ty_mem_agent目录内运行，调整导入路径
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).parent))
    from utils.logger_config import setup_logger, get_logger

# 设置日志
log_level = os.getenv('LOG_LEVEL', 'INFO')
log_file = os.getenv('LOG_FILE', 'logs/ty_mem_agent.log')
setup_logger(level=log_level, log_file=log_file)

# 获取logger
logger = get_logger("Startup")

# 检查依赖
def check_dependencies():
    """检查必要的依赖"""
    required_packages = [
        'qwen_agent',
        'fastapi', 
        'uvicorn',
        'httpx',
        'loguru',
        'pydantic',
        'passlib',
        'python-jose'
    ]
    
    missing = []
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
        except ImportError:
            missing.append(package)
    
    if missing:
        logger.error(f"❌ 缺少依赖包: {', '.join(missing)}")
        logger.info(f"📦 请运行: pip install {' '.join(missing)}")
        return False
    
    return True

# 检查配置
def check_configuration():
    """检查配置文件"""
    env_file = project_root / ".env"
    env_example = project_root / "env_example.txt"
    
    if not env_file.exists():
        if env_example.exists():
            logger.warning("⚠️ 未找到 .env 配置文件")
            logger.info(f"📁 请复制 {env_example} 为 .env 并填入您的配置")
            return False
        else:
            logger.warning("⚠️ 配置文件不存在，将使用默认配置（可能无法正常工作）")
    
    # 检查关键配置
    missing_configs = []
    
    if not os.getenv('DASHSCOPE_API_KEY') and not os.getenv('OPENAI_API_KEY'):
        missing_configs.append("DASHSCOPE_API_KEY 或 OPENAI_API_KEY")
    
    if not os.getenv('MEMOS_API_KEY'):
        missing_configs.append("MEMOS_API_KEY")
    
    if missing_configs:
        logger.warning(f"⚠️ 缺少关键配置: {', '.join(missing_configs)}")
        logger.warning("系统可能无法正常工作，建议先配置相关API密钥")
        
        response = input("是否继续启动？(y/N): ")
        if response.lower() != 'y':
            logger.info("👋 用户选择取消启动")
            return False
    
    return True

def show_banner():
    """显示启动横幅"""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                    TY Memory Agent                           ║
║                    智能记忆助手系统                           ║
║                                                              ║
║  🧠 集成MemOS记忆系统                                        ║
║  🤖 基于QwenAgent框架                                        ║
║  🔧 支持MCP工具调用                                          ║
║  👥 多用户会话管理                                           ║
║  💬 实时聊天交互                                             ║
╚══════════════════════════════════════════════════════════════╝
    """
    # 横幅直接输出到控制台，不通过日志系统
    print(banner)

async def main():
    """主函数"""
    show_banner()
    
    logger.info("🔍 检查系统环境...")
    
    # 检查依赖
    if not check_dependencies():
        return 1
    logger.info("✅ 依赖检查通过")
    
    # 检查配置
    if not check_configuration():
        return 1
    logger.info("✅ 配置检查通过")
    
    # 导入并启动应用
    try:
        from main import TYMemoryAgentApp
        
        app = TYMemoryAgentApp()
        success = await app.run()
        return 0 if success else 1
        
    except ImportError as e:
        logger.error(f"❌ 导入错误: {e}")
        logger.info("📦 请确保所有模块都已正确安装")
        return 1
    except Exception as e:
        logger.error(f"❌ 启动失败: {e}")
        return 1

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("\n👋 用户中断，退出程序")
        sys.exit(0)
