#!/usr/bin/env python3
"""
用户记忆管理模块
管理多用户的个性化记忆和会话状态
"""

import json
import sqlite3
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from loguru import logger

from .memos_client import memory_manager, MemoryScope, MemoryType


@dataclass
class UserProfile:
    """用户画像数据类"""
    user_id: str
    name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    location: Optional[str] = None
    occupation: Optional[str] = None
    interests: List[str] = None
    preferences: Dict[str, Any] = None
    created_at: datetime = None
    updated_at: datetime = None
    
    def __post_init__(self):
        if self.interests is None:
            self.interests = []
        if self.preferences is None:
            self.preferences = {}
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()


@dataclass
class ConversationContext:
    """对话上下文数据类"""
    user_id: str
    session_id: str
    current_topic: Optional[str] = None
    mentioned_entities: List[str] = None
    user_intent: Optional[str] = None
    conversation_history: List[Dict] = None
    last_activity: datetime = None
    
    def __post_init__(self):
        if self.mentioned_entities is None:
            self.mentioned_entities = []
        if self.conversation_history is None:
            self.conversation_history = []
        if self.last_activity is None:
            self.last_activity = datetime.now()


class UserMemoryManager:
    """用户记忆管理器"""
    
    def __init__(self, db_path: str = "user_memory.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """初始化数据库"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    profile_data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversation_contexts (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    context_data TEXT NOT NULL,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_insights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    insight_type TEXT NOT NULL,
                    insight_data TEXT NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
                )
            """)
            
            conn.commit()
    
    def save_user_profile(self, profile: UserProfile) -> bool:
        """保存用户画像"""
        try:
            profile.updated_at = datetime.now()
            profile_json = json.dumps(asdict(profile), default=str)
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO user_profiles (user_id, profile_data, updated_at)
                    VALUES (?, ?, ?)
                """, (profile.user_id, profile_json, profile.updated_at))
                conn.commit()
            
            logger.info(f"💾 保存用户画像: {profile.user_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 保存用户画像失败: {e}")
            return False
    
    def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        """获取用户画像"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT profile_data FROM user_profiles WHERE user_id = ?",
                    (user_id,)
                )
                row = cursor.fetchone()
                
                if row:
                    profile_data = json.loads(row[0])
                    # 处理datetime字段
                    if 'created_at' in profile_data and isinstance(profile_data['created_at'], str):
                        profile_data['created_at'] = datetime.fromisoformat(profile_data['created_at'])
                    if 'updated_at' in profile_data and isinstance(profile_data['updated_at'], str):
                        profile_data['updated_at'] = datetime.fromisoformat(profile_data['updated_at'])
                    
                    return UserProfile(**profile_data)
                else:
                    return None
                    
        except Exception as e:
            logger.error(f"❌ 获取用户画像失败: {e}")
            return None
    
    def update_user_profile(self, user_id: str, updates: Dict[str, Any]) -> bool:
        """更新用户画像"""
        try:
            profile = self.get_user_profile(user_id)
            if not profile:
                # 创建新用户画像
                profile = UserProfile(user_id=user_id)
            
            # 更新字段
            for key, value in updates.items():
                if hasattr(profile, key):
                    setattr(profile, key, value)
            
            return self.save_user_profile(profile)
            
        except Exception as e:
            logger.error(f"❌ 更新用户画像失败: {e}")
            return False
    
    def save_conversation_context(self, context: ConversationContext) -> bool:
        """保存对话上下文"""
        try:
            context.last_activity = datetime.now()
            context_json = json.dumps(asdict(context), default=str)
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO conversation_contexts 
                    (session_id, user_id, context_data, last_activity)
                    VALUES (?, ?, ?, ?)
                """, (context.session_id, context.user_id, context_json, context.last_activity))
                conn.commit()
            
            logger.debug(f"💬 保存对话上下文: {context.session_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 保存对话上下文失败: {e}")
            return False
    
    def get_conversation_context(self, session_id: str) -> Optional[ConversationContext]:
        """获取对话上下文"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT context_data FROM conversation_contexts WHERE session_id = ?",
                    (session_id,)
                )
                row = cursor.fetchone()
                
                if row:
                    context_data = json.loads(row[0])
                    # 处理datetime字段
                    if 'last_activity' in context_data and isinstance(context_data['last_activity'], str):
                        context_data['last_activity'] = datetime.fromisoformat(context_data['last_activity'])
                    
                    return ConversationContext(**context_data)
                else:
                    return None
                    
        except Exception as e:
            logger.error(f"❌ 获取对话上下文失败: {e}")
            return None
    
    def cleanup_expired_sessions(self, hours: int = 24) -> int:
        """清理过期会话"""
        try:
            cutoff_time = datetime.now() - timedelta(hours=hours)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    DELETE FROM conversation_contexts 
                    WHERE last_activity < ?
                """, (cutoff_time,))
                conn.commit()
                
                deleted_count = cursor.rowcount
                logger.info(f"🧹 清理了 {deleted_count} 个过期会话")
                return deleted_count
                
        except Exception as e:
            logger.error(f"❌ 清理过期会话失败: {e}")
            return 0
    
    def save_memory_insight(self, user_id: str, insight_type: str, insight_data: Dict, confidence: float = 0.5) -> bool:
        """保存记忆洞察"""
        try:
            insight_json = json.dumps(insight_data)
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO memory_insights (user_id, insight_type, insight_data, confidence)
                    VALUES (?, ?, ?, ?)
                """, (user_id, insight_type, insight_json, confidence))
                conn.commit()
            
            logger.debug(f"🧠 保存记忆洞察: {user_id} - {insight_type}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 保存记忆洞察失败: {e}")
            return False
    
    def get_memory_insights(self, user_id: str, insight_type: str = None, limit: int = 10) -> List[Dict]:
        """获取记忆洞察"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                if insight_type:
                    cursor = conn.execute("""
                        SELECT insight_type, insight_data, confidence, created_at
                        FROM memory_insights 
                        WHERE user_id = ? AND insight_type = ?
                        ORDER BY created_at DESC LIMIT ?
                    """, (user_id, insight_type, limit))
                else:
                    cursor = conn.execute("""
                        SELECT insight_type, insight_data, confidence, created_at
                        FROM memory_insights 
                        WHERE user_id = ?
                        ORDER BY created_at DESC LIMIT ?
                    """, (user_id, limit))
                
                insights = []
                for row in cursor.fetchall():
                    insights.append({
                        "type": row[0],
                        "data": json.loads(row[1]),
                        "confidence": row[2],
                        "created_at": row[3]
                    })
                
                return insights
                
        except Exception as e:
            logger.error(f"❌ 获取记忆洞察失败: {e}")
            return []


class IntegratedMemorySystem:
    """集成记忆系统
    
    结合本地用户管理和远程MemOS记忆
    """
    
    def __init__(self):
        self.user_manager = UserMemoryManager()
        self.remote_memory = memory_manager
    
    async def initialize_user(self, user_id: str, initial_profile: Dict = None) -> UserProfile:
        """初始化用户"""
        profile = self.user_manager.get_user_profile(user_id)
        
        if not profile:
            # 创建新用户
            profile = UserProfile(user_id=user_id)
            if initial_profile:
                for key, value in initial_profile.items():
                    if hasattr(profile, key):
                        setattr(profile, key, value)
            
            # 保存到本地
            self.user_manager.save_user_profile(profile)
            
            # 同步到远程MemOS
            await self.remote_memory.save_user_profile(user_id, asdict(profile))
            
            logger.info(f"👤 初始化新用户: {user_id}")
        
        return profile
    
    async def update_user_info(self, user_id: str, new_info: Dict) -> bool:
        """更新用户信息"""
        try:
            # 更新本地
            success = self.user_manager.update_user_profile(user_id, new_info)
            
            if success:
                # 同步到远程
                await self.remote_memory.update_user_context(user_id, new_info)
                
                # 保存洞察
                self.user_manager.save_memory_insight(
                    user_id, 
                    "profile_update",
                    {"updated_fields": list(new_info.keys()), "timestamp": datetime.now().isoformat()},
                    confidence=0.9
                )
                
                logger.info(f"🔄 更新用户信息: {user_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ 更新用户信息失败: {e}")
            return False
    
    async def save_conversation(self, user_id: str, session_id: str, message: str, 
                               response: str, context: Dict = None) -> bool:
        """保存对话记录"""
        try:
            # 保存到远程MemOS
            conversation_text = f"用户: {message}\n助手: {response}"
            await self.remote_memory.save_conversation_memory(user_id, conversation_text, context)
            
            # 更新本地上下文
            conv_context = self.user_manager.get_conversation_context(session_id)
            if not conv_context:
                conv_context = ConversationContext(user_id=user_id, session_id=session_id)
            
            # 更新对话历史（保留最近10条）
            conv_context.conversation_history.append({
                "message": message,
                "response": response,
                "timestamp": datetime.now().isoformat(),
                "context": context
            })
            
            if len(conv_context.conversation_history) > 10:
                conv_context.conversation_history = conv_context.conversation_history[-10:]
            
            # 分析和更新上下文
            if context:
                if context.get("topic"):
                    conv_context.current_topic = context["topic"]
                if context.get("entities"):
                    conv_context.mentioned_entities.extend(context["entities"])
                    # 去重并保留最近的
                    conv_context.mentioned_entities = list(set(conv_context.mentioned_entities))[-20:]
            
            self.user_manager.save_conversation_context(conv_context)
            
            logger.debug(f"💬 保存对话: {user_id} - {session_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 保存对话失败: {e}")
            return False
    
    async def get_user_context(self, user_id: str, session_id: str) -> Dict:
        """获取用户完整上下文"""
        try:
            # 获取用户画像
            profile = self.user_manager.get_user_profile(user_id)
            
            # 获取对话上下文
            conv_context = self.user_manager.get_conversation_context(session_id)
            
            # 获取相关记忆
            recent_memories = await self.remote_memory.get_relevant_memories(
                user_id, 
                conv_context.current_topic if conv_context else "",
                context=""
            )
            
            # 获取记忆洞察
            insights = self.user_manager.get_memory_insights(user_id, limit=5)
            
            context = {
                "user_profile": asdict(profile) if profile else {},
                "conversation_context": asdict(conv_context) if conv_context else {},
                "relevant_memories": recent_memories,
                "insights": insights,
                "session_id": session_id
            }
            
            return context
            
        except Exception as e:
            logger.error(f"❌ 获取用户上下文失败: {e}")
            return {}
    
    async def analyze_user_patterns(self, user_id: str) -> Dict:
        """分析用户模式"""
        try:
            insights = self.user_manager.get_memory_insights(user_id, limit=50)
            profile = self.user_manager.get_user_profile(user_id)
            
            patterns = {
                "interaction_frequency": len(insights),
                "common_topics": [],
                "preferences": profile.preferences if profile else {},
                "behavioral_patterns": []
            }
            
            # 分析洞察数据
            topic_counts = {}
            for insight in insights:
                if insight["type"] == "conversation":
                    topic = insight["data"].get("topic")
                    if topic:
                        topic_counts[topic] = topic_counts.get(topic, 0) + 1
            
            patterns["common_topics"] = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            
            # 保存分析结果
            self.user_manager.save_memory_insight(
                user_id,
                "pattern_analysis",
                patterns,
                confidence=0.7
            )
            
            logger.info(f"📊 分析用户模式: {user_id}")
            return patterns
            
        except Exception as e:
            logger.error(f"❌ 分析用户模式失败: {e}")
            return {}


# 全局集成记忆系统实例
integrated_memory = IntegratedMemorySystem()


if __name__ == "__main__":
    # 测试代码
    import asyncio
    
    async def test_user_memory():
        from ty_mem_agent.utils.logger_config import get_logger
        test_logger = get_logger("UserMemoryTest")
        
        system = IntegratedMemorySystem()
        
        # 测试用户初始化
        profile = await system.initialize_user("test_user", {
            "name": "测试用户",
            "age": 25,
            "interests": ["技术", "音乐"]
        })
        test_logger.info(f"👤 用户画像: {profile}")
        
        # 测试对话保存
        await system.save_conversation(
            "test_user",
            "session_123",
            "今天天气怎么样？",
            "今天北京天气晴朗，温度20度。",
            {"topic": "weather", "location": "北京"}
        )
        
        # 测试上下文获取
        context = await system.get_user_context("test_user", "session_123")
        test_logger.info(f"📄 用户上下文: {len(context)} 个字段")
        
        # 测试模式分析
        patterns = await system.analyze_user_patterns("test_user")
        test_logger.info(f"📊 用户模式: {patterns}")
    
    asyncio.run(test_user_memory())
