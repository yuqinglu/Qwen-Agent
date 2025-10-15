#!/usr/bin/env python3
"""
待办事项管理 API
提供RESTful API接口
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from ty_mem_agent.memory.todo_manager import get_todo_manager, TodoStatus
from ty_mem_agent.utils.logger_config import get_logger

logger = get_logger("TodoAPI")

# 创建路由
router = APIRouter(prefix="/api/todos", tags=["todos"])


# 请求模型
class TodoCreateRequest(BaseModel):
    """创建待办请求"""
    title: str
    description: Optional[str] = None
    deadline: Optional[str] = None
    reminder_time: Optional[str] = None
    location: Optional[str] = None
    participants: Optional[List[str]] = None
    priority: Optional[int] = 0
    tags: Optional[List[str]] = None


class TodoUpdateRequest(BaseModel):
    """更新待办请求"""
    title: Optional[str] = None
    description: Optional[str] = None
    deadline: Optional[str] = None
    reminder_time: Optional[str] = None
    location: Optional[str] = None
    participants: Optional[List[str]] = None
    status: Optional[str] = None
    priority: Optional[int] = None
    tags: Optional[List[str]] = None


# API端点
@router.get("/list/{user_id}")
async def get_todos_list(
    user_id: str,
    date: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """获取待办列表
    
    Args:
        user_id: 用户ID
        date: 指定日期 (YYYY-MM-DD)
        status: 状态筛选
        start_date: 开始日期
        end_date: 结束日期
    """
    try:
        todo_manager = get_todo_manager()
        
        if date:
            # 查询指定日期
            todos = todo_manager.get_todos_by_date(user_id, date, status)
        elif start_date or end_date:
            # 查询日期范围
            todos = todo_manager.get_todos_by_range(user_id, start_date, end_date, status)
        else:
            # 查询未完成的待办
            todos = todo_manager.get_pending_todos(user_id, limit=100)
        
        return {
            "success": True,
            "count": len(todos),
            "todos": [todo.to_dict() for todo in todos]
        }
    except Exception as e:
        logger.error(f"❌ 查询待办失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/{user_id}")
async def get_todo_stats(user_id: str):
    """获取待办统计信息"""
    try:
        logger.info(f"📊 获取用户统计信息: {user_id}")
        todo_manager = get_todo_manager()
        
        # 确保传递字符串值而不是枚举对象
        pending_count = todo_manager.get_todos_count(user_id, TodoStatus.PENDING.value)
        completed_count = todo_manager.get_todos_count(user_id, TodoStatus.COMPLETED.value)
        
        # 获取今天的待办
        today = datetime.now().strftime("%Y-%m-%d")
        today_todos = todo_manager.get_todos_by_date(user_id, today, TodoStatus.PENDING.value)
        
        stats = {
            "pending": pending_count,
            "completed": completed_count,
            "today": len(today_todos)
        }
        
        logger.info(f"📊 统计结果: {stats}")
        
        return {
            "success": True,
            "stats": stats
        }
    except Exception as e:
        logger.error(f"❌ 获取统计信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{user_id}/{todo_id}")
async def get_todo(user_id: str, todo_id: int):
    """获取单个待办"""
    try:
        todo_manager = get_todo_manager()
        todo = todo_manager.get_todo(todo_id, user_id)
        
        if not todo:
            raise HTTPException(status_code=404, detail="待办不存在")
        
        return {
            "success": True,
            "todo": todo.to_dict()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 查询待办失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{user_id}")
async def create_todo(user_id: str, request: TodoCreateRequest):
    """创建待办"""
    try:
        todo_manager = get_todo_manager()
        
        todo_data = request.dict(exclude_none=True)
        todo = todo_manager.create_todo(user_id, todo_data)
        
        return {
            "success": True,
            "todo": todo.to_dict(),
            "message": "✅ 待办创建成功"
        }
    except Exception as e:
        logger.error(f"❌ 创建待办失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{user_id}/{todo_id}")
async def update_todo(user_id: str, todo_id: int, request: TodoUpdateRequest):
    """更新待办"""
    try:
        todo_manager = get_todo_manager()
        
        updates = request.dict(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="没有需要更新的字段")
        
        success = todo_manager.update_todo(todo_id, user_id, updates)
        
        if not success:
            raise HTTPException(status_code=404, detail="待办不存在或更新失败")
        
        return {
            "success": True,
            "message": "✅ 待办更新成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 更新待办失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{user_id}/{todo_id}/complete")
async def complete_todo(user_id: str, todo_id: int):
    """标记待办为已完成"""
    try:
        todo_manager = get_todo_manager()
        success = todo_manager.complete_todo(todo_id, user_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="待办不存在")
        
        return {
            "success": True,
            "message": "✅ 待办已完成"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 完成待办失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{user_id}/{todo_id}")
async def delete_todo(user_id: str, todo_id: int):
    """删除待办"""
    try:
        todo_manager = get_todo_manager()
        success = todo_manager.delete_todo(todo_id, user_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="待办不存在")
        
        return {
            "success": True,
            "message": "✅ 待办已删除"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 删除待办失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))



