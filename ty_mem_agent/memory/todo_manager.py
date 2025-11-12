#!/usr/bin/env python3
"""
待办事项管理器
负责待办事项的存储、查询和管理
"""

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum

from ty_mem_agent.config.settings import settings
from ty_mem_agent.utils.logger_config import get_logger

logger = get_logger("TodoManager")


class TodoStatus(str, Enum):
    """待办状态枚举"""
    PENDING = "pending"      # 未完成
    COMPLETED = "completed"  # 已完成
    DELETED = "deleted"      # 已删除
    CANCELLED = "cancelled"  # 已取消


@dataclass
class TodoItem:
    """待办事项数据类"""
    id: Optional[int] = None
    user_id: str = ""
    title: str = ""                    # 事件标题
    description: str = ""              # 事件描述
    deadline: Optional[str] = None     # 截止时间 (ISO 8601格式)
    reminder_time: Optional[str] = None  # 提醒时间 (ISO 8601格式)
    location: Optional[str] = None     # 地点
    participants: Optional[str] = None  # 参与人（JSON数组）
    status: str = TodoStatus.PENDING   # 状态
    priority: int = 0                  # 优先级 (0-低, 1-中, 2-高)
    tags: Optional[str] = None         # 标签 (JSON数组)
    created_at: Optional[str] = None   # 创建时间
    updated_at: Optional[str] = None   # 更新时间
    completed_at: Optional[str] = None # 完成时间
    # 会议相关字段（用于飞书会议管理）
    reserve_id: Optional[str] = None   # 飞书会议预约ID
    event_id: Optional[str] = None     # 飞书日历事件ID
    calendar_id: Optional[str] = None  # 飞书日历ID
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        # 解析JSON字段
        if self.participants:
            try:
                data['participants'] = json.loads(self.participants)
            except:
                data['participants'] = []
        if self.tags:
            try:
                data['tags'] = json.loads(self.tags)
            except:
                data['tags'] = []
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TodoItem':
        """从字典创建"""
        # 处理JSON字段
        if 'participants' in data and isinstance(data['participants'], list):
            data['participants'] = json.dumps(data['participants'], ensure_ascii=False)
        if 'tags' in data and isinstance(data['tags'], list):
            data['tags'] = json.dumps(data['tags'], ensure_ascii=False)
        return cls(**data)


class TodoManager:
    """待办事项管理器"""
    
    def __init__(self, db_path: Optional[str] = None):
        """初始化待办管理器"""
        if db_path is None:
            # 使用配置文件中的路径
            data_dir = Path(settings.DATA_DIR)
            data_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(data_dir / "todos.db")
        else:
            self.db_path = db_path
        
        self.init_database()
        logger.info(f"💾 待办数据库初始化完成: {self.db_path}")
    
    def init_database(self):
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 创建待办表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                deadline TEXT,
                reminder_time TEXT,
                location TEXT,
                participants TEXT,
                status TEXT DEFAULT 'pending',
                priority INTEGER DEFAULT 0,
                tags TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)
        
        # 创建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_id ON todos (user_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_status ON todos (status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_deadline ON todos (deadline)
        """)
        
        # 添加会议相关字段（如果不存在）
        try:
            cursor.execute("ALTER TABLE todos ADD COLUMN reserve_id TEXT")
            logger.info("✅ 添加字段: reserve_id")
        except sqlite3.OperationalError:
            pass  # 字段已存在
        
        try:
            cursor.execute("ALTER TABLE todos ADD COLUMN event_id TEXT")
            logger.info("✅ 添加字段: event_id")
        except sqlite3.OperationalError:
            pass  # 字段已存在
        
        try:
            cursor.execute("ALTER TABLE todos ADD COLUMN calendar_id TEXT")
            logger.info("✅ 添加字段: calendar_id")
        except sqlite3.OperationalError:
            pass  # 字段已存在
        
        conn.commit()
        conn.close()
    
    def create_todo(self, user_id: str, todo_data: Dict[str, Any]) -> TodoItem:
        """创建待办事项"""
        now = datetime.now().isoformat()
        
        # 创建TodoItem
        todo = TodoItem(
            user_id=user_id,
            title=todo_data.get('title', ''),
            description=todo_data.get('description', ''),
            deadline=todo_data.get('deadline'),
            reminder_time=todo_data.get('reminder_time'),
            location=todo_data.get('location'),
            participants=json.dumps(todo_data.get('participants', []), ensure_ascii=False),
            status=todo_data.get('status', TodoStatus.PENDING),
            priority=todo_data.get('priority', 0),
            tags=json.dumps(todo_data.get('tags', []), ensure_ascii=False),
            created_at=now,
            updated_at=now,
            reserve_id=todo_data.get('reserve_id'),  # 会议预约ID
            event_id=todo_data.get('event_id'),      # 日历事件ID
            calendar_id=todo_data.get('calendar_id') # 日历ID
        )
        
        # 保存到数据库
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO todos (
                user_id, title, description, deadline, reminder_time,
                location, participants, status, priority, tags,
                created_at, updated_at, reserve_id, event_id, calendar_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            todo.user_id, todo.title, todo.description, todo.deadline,
            todo.reminder_time, todo.location, todo.participants,
            todo.status, todo.priority, todo.tags,
            todo.created_at, todo.updated_at,
            todo.reserve_id, todo.event_id, todo.calendar_id
        ))
        
        todo.id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"✅ 创建待办: {todo.title} (ID: {todo.id})")
        return todo
    
    def get_todo(self, todo_id: int, user_id: str) -> Optional[TodoItem]:
        """获取单个待办"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM todos WHERE id = ? AND user_id = ?
        """, (todo_id, user_id))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return TodoItem(**dict(row))
        return None
    
    def get_todos_by_date(
        self, 
        user_id: str, 
        date: str,
        status: Optional[str] = None
    ) -> List[TodoItem]:
        """获取指定日期的待办列表
        
        Args:
            user_id: 用户ID
            date: 日期字符串 (YYYY-MM-DD)
            status: 状态筛选，None表示所有非删除状态
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 日期范围
        start_time = f"{date}T00:00:00"
        end_time = f"{date}T23:59:59"
        
        if status:
            cursor.execute("""
                SELECT * FROM todos 
                WHERE user_id = ? 
                AND deadline >= ? 
                AND deadline <= ?
                AND status = ?
                ORDER BY deadline ASC
            """, (user_id, start_time, end_time, status))
        else:
            # 默认排除已删除的
            cursor.execute("""
                SELECT * FROM todos 
                WHERE user_id = ? 
                AND deadline >= ? 
                AND deadline <= ?
                AND status != ?
                ORDER BY deadline ASC
            """, (user_id, start_time, end_time, TodoStatus.DELETED))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [TodoItem(**dict(row)) for row in rows]
    
    def get_todos_by_range(
        self,
        user_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[TodoItem]:
        """获取时间范围内的待办列表"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = "SELECT * FROM todos WHERE user_id = ?"
        params = [user_id]
        
        if start_date:
            query += " AND deadline >= ?"
            params.append(start_date)
        
        if end_date:
            query += " AND deadline <= ?"
            params.append(end_date)
        
        if status:
            query += " AND status = ?"
            params.append(status)
        else:
            query += " AND status != ?"
            params.append(TodoStatus.DELETED)
        
        query += " ORDER BY deadline ASC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [TodoItem(**dict(row)) for row in rows]
    
    def get_pending_todos(self, user_id: str, limit: int = 10) -> List[TodoItem]:
        """获取未完成的待办列表"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM todos 
            WHERE user_id = ? AND status = ?
            ORDER BY deadline ASC
            LIMIT ?
        """, (user_id, TodoStatus.PENDING, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [TodoItem(**dict(row)) for row in rows]
    
    def update_todo(self, todo_id: int, user_id: str, updates: Dict[str, Any]) -> bool:
        """更新待办事项"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 构建更新语句
        update_fields = []
        params = []
        
        for key, value in updates.items():
            if key in ['participants', 'tags'] and isinstance(value, list):
                value = json.dumps(value, ensure_ascii=False)
            update_fields.append(f"{key} = ?")
            params.append(value)
        
        # 添加更新时间
        update_fields.append("updated_at = ?")
        params.append(datetime.now().isoformat())
        
        # 添加WHERE条件参数
        params.extend([todo_id, user_id])
        
        query = f"UPDATE todos SET {', '.join(update_fields)} WHERE id = ? AND user_id = ?"
        
        cursor.execute(query, params)
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        if affected > 0:
            logger.info(f"✅ 更新待办 ID: {todo_id}")
            return True
        return False
    
    def complete_todo(self, todo_id: int, user_id: str) -> bool:
        """标记待办为已完成"""
        now = datetime.now().isoformat()
        return self.update_todo(todo_id, user_id, {
            'status': TodoStatus.COMPLETED,
            'completed_at': now
        })
    
    def delete_todo(self, todo_id: int, user_id: str) -> bool:
        """删除待办（软删除）"""
        return self.update_todo(todo_id, user_id, {
            'status': TodoStatus.DELETED
        })
    
    def check_conflicts(
        self, 
        user_id: str, 
        deadline: str, 
        duration_minutes: int = 60,
        exclude_todo_id: Optional[int] = None
    ) -> List[TodoItem]:
        """检查时间冲突
        
        Args:
            user_id: 用户ID
            deadline: 待办时间
            duration_minutes: 持续时间（分钟）
            exclude_todo_id: 要排除的待办ID（避免自己与自己冲突）
        """
        # 计算时间范围
        dt = datetime.fromisoformat(deadline)
        start_time = (dt - timedelta(minutes=duration_minutes)).isoformat()
        end_time = (dt + timedelta(minutes=duration_minutes)).isoformat()
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 构建查询条件
        where_conditions = [
            "user_id = ?",
            "status = ?", 
            "deadline >= ?",
            "deadline <= ?"
        ]
        params = [user_id, TodoStatus.PENDING, start_time, end_time]
        
        # 如果需要排除特定待办
        if exclude_todo_id is not None:
            where_conditions.append("id != ?")
            params.append(exclude_todo_id)
        
        query = f"""
            SELECT * FROM todos 
            WHERE {' AND '.join(where_conditions)}
            ORDER BY deadline ASC
        """
        
        cursor.execute(query, params)
        
        rows = cursor.fetchall()
        conn.close()
        
        return [TodoItem(**dict(row)) for row in rows]
    
    def get_todos_count(self, user_id: str, status: Optional[str] = None) -> int:
        """获取待办数量"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if status:
            cursor.execute("""
                SELECT COUNT(*) FROM todos WHERE user_id = ? AND status = ?
            """, (user_id, status))
        else:
            cursor.execute("""
                SELECT COUNT(*) FROM todos WHERE user_id = ? AND status != ?
            """, (user_id, TodoStatus.DELETED))
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count
    
    def get_todo_by_event_id(self, user_id: str, event_id: str) -> Optional[TodoItem]:
        """根据 event_id 查找待办事项（用于会议更新时同步待办）"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM todos 
            WHERE user_id = ? AND event_id = ? AND status != ?
            LIMIT 1
        """, (user_id, event_id, TodoStatus.DELETED))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return TodoItem(**dict(row))
        return None


# 全局单例
_todo_manager = None


def  get_todo_manager() -> TodoManager:
    """获取待办管理器单例"""
    global _todo_manager
    if _todo_manager is None:
        _todo_manager = TodoManager()
    return _todo_manager

