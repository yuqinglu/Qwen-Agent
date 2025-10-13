#!/usr/bin/env python3
"""
用户数据库模块
使用SQLite持久化存储用户数据
"""

import sqlite3
import json
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime
from loguru import logger


class UserDatabase:
    """用户数据库管理器"""
    
    def __init__(self, db_path: str = None):
        """初始化数据库"""
        if db_path is None:
            # 使用配置文件中的路径
            from ty_mem_agent.config.settings import settings
            self.db_path = Path(settings.USERS_DB_PATH)
        else:
            self.db_path = Path(db_path)
        self._ensure_db_directory()
        self._init_database()
    
    def _ensure_db_directory(self):
        """确保数据库目录存在"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
    
    def _get_connection(self):
        """获取数据库连接"""
        return sqlite3.connect(str(self.db_path))
    
    def _init_database(self):
        """初始化数据库表"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # 创建用户表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT,
                    hashed_password TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_login TEXT
                )
            ''')
            
            # 创建会话表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_activity TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # 创建索引
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_username ON users (username)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_sessions ON sessions (user_id)
            ''')
            
            conn.commit()
            conn.close()
            
            logger.info(f"💾 用户数据库初始化完成: {self.db_path}")
            
        except Exception as e:
            logger.error(f"❌ 数据库初始化失败: {e}")
            raise
    
    # ========== 用户操作 ==========
    
    def save_user(self, user_data: Dict) -> bool:
        """保存用户"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, username, email, hashed_password, is_active, created_at, last_login)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_data['user_id'],
                user_data['username'],
                user_data.get('email'),
                user_data['hashed_password'],
                1 if user_data.get('is_active', True) else 0,
                user_data.get('created_at', datetime.now().isoformat()),
                user_data.get('last_login')
            ))
            
            conn.commit()
            conn.close()
            
            logger.debug(f"💾 保存用户: {user_data['username']}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 保存用户失败: {e}")
            return False
    
    def get_user(self, user_id: str) -> Optional[Dict]:
        """获取用户"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return {
                    'user_id': row[0],
                    'username': row[1],
                    'email': row[2],
                    'hashed_password': row[3],
                    'is_active': bool(row[4]),
                    'created_at': row[5],
                    'last_login': row[6]
                }
            
            return None
            
        except Exception as e:
            logger.error(f"❌ 获取用户失败: {e}")
            return None
    
    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """根据用户名获取用户"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return {
                    'user_id': row[0],
                    'username': row[1],
                    'email': row[2],
                    'hashed_password': row[3],
                    'is_active': bool(row[4]),
                    'created_at': row[5],
                    'last_login': row[6]
                }
            
            return None
            
        except Exception as e:
            logger.error(f"❌ 获取用户失败: {e}")
            return None
    
    def get_all_users(self) -> List[Dict]:
        """获取所有用户"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM users')
            rows = cursor.fetchall()
            conn.close()
            
            users = []
            for row in rows:
                users.append({
                    'user_id': row[0],
                    'username': row[1],
                    'email': row[2],
                    'hashed_password': row[3],
                    'is_active': bool(row[4]),
                    'created_at': row[5],
                    'last_login': row[6]
                })
            
            return users
            
        except Exception as e:
            logger.error(f"❌ 获取所有用户失败: {e}")
            return []
    
    def update_user(self, user_id: str, updates: Dict) -> bool:
        """更新用户"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # 构建更新语句
            fields = []
            values = []
            
            allowed_fields = ['email', 'is_active', 'last_login']
            for field, value in updates.items():
                if field in allowed_fields:
                    fields.append(f"{field} = ?")
                    if field == 'is_active':
                        values.append(1 if value else 0)
                    else:
                        values.append(value)
            
            if not fields:
                return False
            
            values.append(user_id)
            query = f"UPDATE users SET {', '.join(fields)} WHERE user_id = ?"
            
            cursor.execute(query, values)
            conn.commit()
            conn.close()
            
            logger.debug(f"💾 更新用户: {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 更新用户失败: {e}")
            return False
    
    def delete_user(self, user_id: str) -> bool:
        """删除用户"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
            conn.commit()
            conn.close()
            
            logger.info(f"🗑️ 删除用户: {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 删除用户失败: {e}")
            return False
    
    # ========== 会话操作 ==========
    
    def save_session(self, session_data: Dict) -> bool:
        """保存会话"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO sessions 
                (session_id, user_id, created_at, last_activity, is_active)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                session_data['session_id'],
                session_data['user_id'],
                session_data.get('created_at', datetime.now().isoformat()),
                session_data.get('last_activity', datetime.now().isoformat()),
                1 if session_data.get('is_active', True) else 0
            ))
            
            conn.commit()
            conn.close()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 保存会话失败: {e}")
            return False
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        """获取会话"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM sessions WHERE session_id = ?', (session_id,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return {
                    'session_id': row[0],
                    'user_id': row[1],
                    'created_at': row[2],
                    'last_activity': row[3],
                    'is_active': bool(row[4])
                }
            
            return None
            
        except Exception as e:
            logger.error(f"❌ 获取会话失败: {e}")
            return None
    
    def update_session_activity(self, session_id: str) -> bool:
        """更新会话活动时间"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE sessions 
                SET last_activity = ? 
                WHERE session_id = ?
            ''', (datetime.now().isoformat(), session_id))
            
            conn.commit()
            conn.close()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 更新会话活动时间失败: {e}")
            return False
    
    def deactivate_session(self, session_id: str) -> bool:
        """停用会话"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE sessions 
                SET is_active = 0 
                WHERE session_id = ?
            ''', (session_id,))
            
            conn.commit()
            conn.close()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 停用会话失败: {e}")
            return False
    
    def get_user_sessions(self, user_id: str) -> List[Dict]:
        """获取用户的所有会话"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM sessions 
                WHERE user_id = ? 
                ORDER BY last_activity DESC
            ''', (user_id,))
            
            rows = cursor.fetchall()
            conn.close()
            
            sessions = []
            for row in rows:
                sessions.append({
                    'session_id': row[0],
                    'user_id': row[1],
                    'created_at': row[2],
                    'last_activity': row[3],
                    'is_active': bool(row[4])
                })
            
            return sessions
            
        except Exception as e:
            logger.error(f"❌ 获取用户会话失败: {e}")
            return []
    
    def cleanup_old_sessions(self, days: int = 7) -> int:
        """清理旧会话"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
            
            cursor.execute('''
                DELETE FROM sessions 
                WHERE last_activity < ? AND is_active = 0
            ''', (cutoff_date,))
            
            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()
            
            logger.info(f"🧹 清理旧会话: {deleted_count} 个")
            return deleted_count
            
        except Exception as e:
            logger.error(f"❌ 清理旧会话失败: {e}")
            return 0
    
    # ========== 统计操作 ==========
    
    def get_user_count(self) -> int:
        """获取用户总数"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM users')
            count = cursor.fetchone()[0]
            conn.close()
            
            return count
            
        except Exception as e:
            logger.error(f"❌ 获取用户总数失败: {e}")
            return 0
    
    def get_active_user_count(self) -> int:
        """获取活跃用户总数"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM users WHERE is_active = 1')
            count = cursor.fetchone()[0]
            conn.close()
            
            return count
            
        except Exception as e:
            logger.error(f"❌ 获取活跃用户总数失败: {e}")
            return 0


# 辅助函数
from datetime import timedelta

if __name__ == "__main__":
    # 测试数据库
    print("🧪 测试用户数据库...")
    
    db = UserDatabase("test_users.db")
    
    # 测试保存用户
    user_data = {
        'user_id': 'user_test_001',
        'username': 'testuser',
        'email': 'test@example.com',
        'hashed_password': 'hashed_password_here',
        'is_active': True,
        'created_at': datetime.now().isoformat()
    }
    
    db.save_user(user_data)
    print(f"✅ 保存用户: {user_data['username']}")
    
    # 测试获取用户
    user = db.get_user_by_username('testuser')
    print(f"✅ 获取用户: {user}")
    
    # 测试统计
    print(f"📊 用户总数: {db.get_user_count()}")
    print(f"📊 活跃用户: {db.get_active_user_count()}")
    
    print("🎉 测试完成！")

