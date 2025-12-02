#!/usr/bin/env python3
"""
TY Memory Agent 启动脚本
确保项目路径正确设置，支持简洁的绝对导入
"""

import sys
import os
from pathlib import Path

def setup_project_path():
    """设置项目路径，确保绝对导入正常工作"""
    # 获取项目根目录
    current_dir = Path(__file__).parent
    project_root = current_dir.parent
    
    # 添加项目根目录到Python路径
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    
    # 设置环境变量
    os.environ['TY_MEM_AGENT_ROOT'] = str(project_root)
    
    return project_root

def main():
    """主函数"""
    print("🚀 设置TY Memory Agent项目路径...")
    
    # 设置项目路径
    project_root = setup_project_path()
    print(f"📁 项目根目录: {project_root}")
    
    # 验证导入
    try:
        import ty_mem_agent
        print("✅ ty_mem_agent模块导入成功")
        
        # 测试核心组件
        from ty_mem_agent.config.settings import settings
        print(f"✅ 配置模块: {settings.PROJECT_NAME}")
        
        from ty_mem_agent.utils.logger_config import get_logger
        logger = get_logger("Startup")
        logger.info("✅ 日志系统正常")
        
        print("🎉 项目路径设置完成，所有模块可以正常导入！")
        return True
        
    except ImportError as e:
        print(f"❌ 导入失败: {e}")
        return False

if __name__ == "__main__":
    main()
