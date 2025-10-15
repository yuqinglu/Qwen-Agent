#!/usr/bin/env python3
"""
清空待办数据库脚本
用于清理所有待办数据，方便重新测试
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from ty_mem_agent.memory.todo_manager import get_todo_manager
from ty_mem_agent.config.settings import settings
from loguru import logger

def clear_all_todos():
    """清空所有待办数据"""
    try:
        logger.info("🧹 开始清空待办数据库...")
        
        # 获取待办管理器
        todo_manager = get_todo_manager()
        
        # 获取所有待办（使用一个很大的日期范围）
        all_todos = todo_manager.get_todos_by_range("test_user", "1900-01-01", "2100-12-31")
        logger.info(f"📋 发现 {len(all_todos)} 个待办事项")
        
        if not all_todos:
            logger.info("✅ 数据库已经是空的，无需清理")
            return
        
        # 删除所有待办
        deleted_count = 0
        for todo in all_todos:
            try:
                todo_manager.delete_todo(todo.id, todo.user_id)
                deleted_count += 1
                logger.debug(f"🗑️ 已删除待办: {todo.title} (ID: {todo.id})")
            except Exception as e:
                logger.error(f"❌ 删除待办失败 ID {todo.id}: {e}")
        
        logger.info(f"✅ 成功删除 {deleted_count} 个待办事项")
        
        # 验证清理结果
        remaining_todos = todo_manager.get_todos_by_range("test_user", "1900-01-01", "2100-12-31")
        if len(remaining_todos) == 0:
            logger.info("🎉 数据库已完全清空！")
        else:
            logger.warning(f"⚠️ 仍有 {len(remaining_todos)} 个待办未删除")
            
    except Exception as e:
        logger.error(f"❌ 清空数据库失败: {e}")
        raise

def show_database_info():
    """显示数据库信息"""
    try:
        # 获取数据库路径
        db_path = os.path.join(settings.DATA_DIR, "todos.db")
        logger.info("📊 数据库信息:")
        logger.info(f"   - 数据库路径: {db_path}")
        logger.info(f"   - 数据库存在: {os.path.exists(db_path)}")
        
        if os.path.exists(db_path):
            file_size = os.path.getsize(db_path)
            logger.info(f"   - 文件大小: {file_size} 字节")
        
    except Exception as e:
        logger.error(f"❌ 获取数据库信息失败: {e}")

def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("🧹 待办数据库清理工具")
    logger.info("=" * 60)
    
    # 显示数据库信息
    show_database_info()
    
    # 确认操作
    print("\n⚠️  警告：此操作将删除所有待办数据，且无法恢复！")
    try:
        confirm = input("确认继续？(输入 'yes' 确认): ").strip().lower()
    except EOFError:
        # 非交互式环境，直接继续
        logger.info("非交互式环境，自动确认继续...")
        confirm = 'yes'
    
    if confirm != 'yes':
        logger.info("❌ 操作已取消")
        return
    
    # 执行清理
    clear_all_todos()
    
    logger.info("=" * 60)
    logger.info("✅ 清理完成！现在可以运行 test_todo.py 进行测试")
    logger.info("=" * 60)

if __name__ == "__main__":
    main()
