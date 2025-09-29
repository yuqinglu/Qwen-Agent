#!/usr/bin/env python3
"""
用户管理模块
处理用户认证、会话管理和权限控制
"""

import jwt
import hashlib
import secrets
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from passlib.context import CryptContext
from loguru import logger

from ty_mem_agent.config.settings import settings


@dataclass
class User:
    """用户数据类"""
    user_id: str
    username: str
    email: Optional[str] = None
    hashed_password: str = ""
    is_active: bool = True
    created_at: datetime = None
    last_login: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


@dataclass
class Session:
    """会话数据类"""
    session_id: str
    user_id: str
    created_at: datetime
    last_activity: datetime
    is_active: bool = True
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.last_activity is None:
            self.last_activity = datetime.now()


class UserManager:
    """用户管理器"""
    
    def __init__(self):
        # 使用更兼容的密码哈希方案
        self.pwd_context = CryptContext(schemes=["pbkdf2_sha256", "bcrypt"], deprecated="auto")
        self.users: Dict[str, User] = {}  # 内存存储，生产环境应使用数据库
        self.sessions: Dict[str, Session] = {}
        self.active_sessions: Dict[str, str] = {}  # user_id -> session_id
    
    def hash_password(self, password: str) -> str:
        """哈希密码"""
        return self.pwd_context.hash(password)
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """验证密码"""
        return self.pwd_context.verify(plain_password, hashed_password)
    
    def create_user(self, username: str, password: str, email: str = None) -> Optional[User]:
        """创建用户"""
        try:
            # 检查用户名是否已存在
            if any(user.username == username for user in self.users.values()):
                logger.warning(f"用户名已存在: {username}")
                return None
            
            # 生成用户ID
            user_id = self._generate_user_id(username)
            
            # 创建用户
            user = User(
                user_id=user_id,
                username=username,
                email=email,
                hashed_password=self.hash_password(password)
            )
            
            self.users[user_id] = user
            logger.info(f"👤 创建用户: {username} ({user_id})")
            return user
            
        except Exception as e:
            logger.error(f"❌ 创建用户失败: {e}")
            return None
    
    def authenticate_user(self, username: str, password: str) -> Optional[User]:
        """认证用户"""
        try:
            # 查找用户
            user = None
            for u in self.users.values():
                if u.username == username and u.is_active:
                    user = u
                    break
            
            if not user:
                logger.warning(f"用户不存在或已禁用: {username}")
                return None
            
            # 验证密码
            if not self.verify_password(password, user.hashed_password):
                logger.warning(f"密码错误: {username}")
                return None
            
            # 更新最后登录时间
            user.last_login = datetime.now()
            logger.info(f"🔐 用户认证成功: {username}")
            return user
            
        except Exception as e:
            logger.error(f"❌ 用户认证失败: {e}")
            return None
    
    def create_session(self, user_id: str) -> Optional[Session]:
        """创建会话"""
        try:
            # 检查用户是否存在
            if user_id not in self.users:
                logger.warning(f"用户不存在: {user_id}")
                return None
            
            # 生成会话ID
            session_id = self._generate_session_id()
            
            # 创建会话
            session = Session(
                session_id=session_id,
                user_id=user_id,
                created_at=datetime.now(),
                last_activity=datetime.now()
            )
            
            self.sessions[session_id] = session
            self.active_sessions[user_id] = session_id
            
            logger.info(f"📱 创建会话: {user_id} - {session_id}")
            return session
            
        except Exception as e:
            logger.error(f"❌ 创建会话失败: {e}")
            return None
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """获取会话"""
        session = self.sessions.get(session_id)
        if session and session.is_active:
            # 检查会话是否过期
            timeout = timedelta(minutes=settings.CHAT_CONFIG.get("session_timeout_minutes", 60))
            if datetime.now() - session.last_activity > timeout:
                self.end_session(session_id)
                return None
            
            # 更新活动时间
            session.last_activity = datetime.now()
            return session
        
        return None
    
    def get_user_session(self, user_id: str) -> Optional[Session]:
        """获取用户的活跃会话"""
        session_id = self.active_sessions.get(user_id)
        if session_id:
            return self.get_session(session_id)
        return None
    
    def end_session(self, session_id: str) -> bool:
        """结束会话"""
        try:
            session = self.sessions.get(session_id)
            if session:
                session.is_active = False
                
                # 从活跃会话中移除
                if session.user_id in self.active_sessions:
                    if self.active_sessions[session.user_id] == session_id:
                        del self.active_sessions[session.user_id]
                
                logger.info(f"📱 结束会话: {session_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ 结束会话失败: {e}")
            return False
    
    def create_access_token(self, user_id: str) -> str:
        """创建访问令牌"""
        # 使用UTC时间避免时区问题
        from datetime import timezone
        now = datetime.now(timezone.utc)
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        to_encode = {
            "sub": user_id,
            "exp": expire,
            "iat": now,
            "type": "access_token"
        }
        
        encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")
        return encoded_jwt
    
    def verify_access_token(self, token: str) -> Optional[str]:
        """验证访问令牌"""
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            user_id: str = payload.get("sub")
            
            if user_id is None:
                return None
            
            # 检查用户是否存在且活跃
            user = self.users.get(user_id)
            if not user or not user.is_active:
                return None
            
            return user_id
            
        except jwt.ExpiredSignatureError:
            logger.warning("访问令牌已过期")
            return None
        except jwt.PyJWTError:
            logger.warning("访问令牌无效")
            return None
    
    def get_user(self, user_id: str) -> Optional[User]:
        """获取用户"""
        return self.users.get(user_id)
    
    def get_user_by_username(self, username: str) -> Optional[User]:
        """根据用户名获取用户"""
        for user in self.users.values():
            if user.username == username:
                return user
        return None
    
    def update_user(self, user_id: str, updates: Dict) -> bool:
        """更新用户信息"""
        try:
            user = self.users.get(user_id)
            if not user:
                return False
            
            # 更新允许的字段
            allowed_fields = ['email', 'is_active']
            for field, value in updates.items():
                if field in allowed_fields and hasattr(user, field):
                    setattr(user, field, value)
            
            logger.info(f"👤 更新用户: {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 更新用户失败: {e}")
            return False
    
    def get_active_users(self) -> List[User]:
        """获取活跃用户列表"""
        return [user for user in self.users.values() if user.is_active]
    
    def get_user_stats(self) -> Dict:
        """获取用户统计信息"""
        total_users = len(self.users)
        active_users = len([u for u in self.users.values() if u.is_active])
        active_sessions = len([s for s in self.sessions.values() if s.is_active])
        
        return {
            "total_users": total_users,
            "active_users": active_users,
            "active_sessions": active_sessions,
            "registered_today": len([
                u for u in self.users.values() 
                if u.created_at and u.created_at.date() == datetime.now().date()
            ])
        }
    
    def cleanup_expired_sessions(self) -> int:
        """清理过期会话"""
        try:
            timeout = timedelta(minutes=settings.CHAT_CONFIG.get("session_timeout_minutes", 60))
            cutoff_time = datetime.now() - timeout
            
            expired_sessions = []
            for session_id, session in self.sessions.items():
                if session.last_activity < cutoff_time:
                    expired_sessions.append(session_id)
            
            for session_id in expired_sessions:
                self.end_session(session_id)
            
            logger.info(f"🧹 清理过期会话: {len(expired_sessions)} 个")
            return len(expired_sessions)
            
        except Exception as e:
            logger.error(f"❌ 清理过期会话失败: {e}")
            return 0
    
    def _generate_user_id(self, username: str) -> str:
        """生成用户ID"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        hash_input = f"{username}_{timestamp}_{secrets.token_hex(8)}"
        return f"user_{hashlib.md5(hash_input.encode()).hexdigest()[:12]}"
    
    def _generate_session_id(self) -> str:
        """生成会话ID"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        random_part = secrets.token_hex(12)
        return f"session_{timestamp}_{random_part}"


# 全局用户管理器实例
user_manager = UserManager()


# 创建默认用户（用于测试）
def init_default_users():
    """初始化默认用户"""
    try:
        # 创建测试用户
        if not user_manager.get_user_by_username("admin"):
            user_manager.create_user("admin", "admin123", "admin@example.com")
        
        if not user_manager.get_user_by_username("test"):
            user_manager.create_user("test", "test123", "test@example.com")
        
        logger.info("👥 默认用户初始化完成")
        
    except Exception as e:
        logger.error(f"❌ 默认用户初始化失败: {e}")


if __name__ == "__main__":
    # 独立运行时的测试代码
    import sys
    import os
    
    # 添加项目根目录到Python路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(current_dir))
    sys.path.insert(0, project_root)
    
    # 使用简洁的绝对导入
    from ty_mem_agent.config.settings import settings
    from ty_mem_agent.utils.logger_config import get_logger
    
    def test_user_manager():
        """测试用户管理功能"""
        print("🧪 开始测试UserManager...")
        
        manager = UserManager()
        
        # 创建用户
        user = manager.create_user("testuser", "pass123", "test@example.com")
        print(f"👤 创建用户: {user.user_id if user else '失败'}")
        
        # 认证用户
        auth_user = manager.authenticate_user("testuser", "pass123")
        print(f"🔐 认证用户: {auth_user.user_id if auth_user else '失败'}")
        
        # 创建会话
        session = manager.create_session(user.user_id) if user else None
        print(f"📱 创建会话: {session.session_id if session else '失败'}")
        
        # 创建令牌
        token = manager.create_access_token(user.user_id) if user else None
        print(f"🎫 访问令牌: {'已生成' if token else '失败'}")
        
        # 验证令牌
        verified_user_id = manager.verify_access_token(token) if token else None
        print(f"✅ 验证令牌: {verified_user_id or '失败'}")
        
        # 用户统计
        stats = manager.get_user_stats()
        print(f"📊 用户统计: {stats}")
        
        print("🎉 UserManager测试完成！")
    
    test_user_manager()
