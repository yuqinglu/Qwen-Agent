#!/usr/bin/env python3
"""
用户记忆管理模块
管理多用户的个性化记忆和会话状态
"""

import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any, Iterator
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from loguru import logger

# 添加QwenAgent路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from qwen_agent.llm import get_chat_model
from qwen_agent.llm.schema import Message, SYSTEM, USER, ASSISTANT

from ty_mem_agent.memory.memos_client import memory_manager, MemoryScope, MemoryType


@dataclass
class UserProfile:
    """用户画像数据类"""
    user_id: str
    name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    location: Optional[str] = None
    home_address: Optional[str] = None  # 家庭住址
    occupation: Optional[str] = None
    interests: List[str] = None
    preferences: Dict[str, Any] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    
    def __post_init__(self):
        if self.interests is None:
            self.interests = []
        if self.preferences is None:
            self.preferences = {}
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if self.updated_at is None:
            self.updated_at = datetime.now().isoformat()


@dataclass
class ConversationContext:
    """对话上下文数据类"""
    user_id: str
    session_id: str
    current_topic: Optional[str] = None
    mentioned_entities: List[str] = None
    user_intent: Optional[str] = None
    conversation_history: List[Dict] = None
    last_activity: Optional[str] = None
    
    def __post_init__(self):
        if self.mentioned_entities is None:
            self.mentioned_entities = []
        if self.conversation_history is None:
            self.conversation_history = []
        if self.last_activity is None:
            self.last_activity = datetime.now().isoformat()


class UserMemoryManager:
    """用户记忆管理器"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            # 使用配置文件中的路径
            from ty_mem_agent.config.settings import settings
            self.db_path = settings.USER_MEMORY_DB_PATH
            # 确保目录存在
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
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
            profile.updated_at = datetime.now().isoformat()
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
                    # 保持datetime字段为字符串格式，避免JSON序列化问题
                    # 注意：这里不再将字符串转换回datetime对象
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
            context.last_activity = datetime.now().isoformat()
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
                    # 保持datetime字段为字符串格式，避免JSON序列化问题
                    # 注意：这里不再将字符串转换回datetime对象
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
                    # 确保created_at是字符串格式，避免JSON序列化问题
                    created_at = row[3]
                    if hasattr(created_at, 'isoformat'):
                        created_at = created_at.isoformat()
                    elif created_at is None:
                        created_at = ""
                    
                    insights.append({
                        "type": row[0],
                        "data": json.loads(row[1]),
                        "confidence": row[2],
                        "created_at": created_at
                    })
                
                return insights
                
        except Exception as e:
            logger.error(f"❌ 获取记忆洞察失败: {e}")
            return []


class IntegratedMemorySystem:
    """集成记忆系统
    
    结合本地用户管理和远程MemOS记忆，实现完整的用户记忆管理。
    
    架构设计：
    ┌─────────────────────────────────────────────────────────────┐
    │                IntegratedMemorySystem                       │
    ├─────────────────────────────────────────────────────────────┤
    │  user_manager (UserMemoryManager)                           │
    │  ├── 本地SQLite数据库存储                                   │
    │  ├── 用户画像 (UserProfile)                                │
    │  ├── 对话上下文 (ConversationContext)                      │
    │  └── 记忆洞察 (MemoryInsights)                             │
    │                                                             │
    │  remote_memory (EnhancedMemoryManager)                     │
    │  ├── 远程MemOS API + 本地缓存                              │
    │  ├── 对话记忆存储 (原始对话内容)                            │
    │  ├── 智能记忆检索 (语义搜索)                               │
    │  └── 会话记忆管理 (跨会话关联)                             │
    │                                                             │
    │  llm (LLM模型)                                             │
    │  ├── 对话上下文分析                                         │
    │  ├── 用户画像提取                                           │
    │  └── 智能洞察生成                                           │
    └─────────────────────────────────────────────────────────────┘
    
    数据流向：
    1. 用户输入 → user_manager (存储结构化数据) → remote_memory (存储原始对话)
    2. 记忆检索 → user_manager (快速访问) + remote_memory (语义搜索)
    3. 智能分析 → llm (上下文分析) → user_manager (保存洞察)
    
    协同工作模式：
    - user_manager: 负责结构化数据的快速存储和查询（毫秒级响应）
    - remote_memory: 负责非结构化数据的智能存储和检索（语义搜索）
    - llm: 负责智能分析和洞察生成（上下文理解、用户画像提取）
    
    使用场景：
    - 聊天对话: 结合用户画像、对话历史、相关记忆提供个性化回复
    - 用户画像: 从对话中智能提取和更新用户信息
    - 记忆检索: 基于语义相似度查找相关历史对话
    - 行为分析: 分析用户模式，生成个性化洞察
    """
    
    def __init__(self, llm=None):
        # ==================== 记忆系统组件初始化 ====================
        
        # 1. 本地用户管理器 (UserMemoryManager)
        # 功能: 管理用户画像、对话上下文、记忆洞察
        # 存储: 本地SQLite数据库 (user_memory.db)
        # 特点: 快速访问、结构化数据、复杂查询支持
        self.user_manager = UserMemoryManager()
        
        # 2. 远程记忆管理器 (EnhancedMemoryManager) 
        # 功能: 管理对话记忆、智能检索、会话记忆
        # 存储: 远程MemOS API + 本地内存缓存
        # 特点: 语义搜索、跨会话关联、云端同步
        self.remote_memory = memory_manager
        
        # 3. LLM模型 (用于智能分析)
        # 功能: 对话上下文分析、用户画像提取、智能洞察生成
        # 特点: 自然语言理解、智能推理、个性化分析
        if llm is None:
            from ty_mem_agent.config.settings import get_llm_config
            llm_config = get_llm_config()
            self.llm = get_chat_model(llm_config)
        else:
            self.llm = llm
        
        logger.info("✅ 集成记忆系统初始化完成")
    
    async def initialize_user(self, user_id: str, initial_profile: Dict = None) -> UserProfile:
        """初始化用户
        
        记忆组件使用：
        - user_manager: 查询和创建用户画像
        - remote_memory: 暂不使用（云端不支持用户画像写入）
        
        数据流：
        1. 查询本地用户画像 (user_manager)
        2. 如果不存在，创建新用户画像 (user_manager)
        3. 保存到本地数据库 (user_manager)
        """
        # 1. 查询本地用户画像
        profile = self.user_manager.get_user_profile(user_id)
        
        if not profile:
            # 2. 创建新用户画像
            profile = UserProfile(user_id=user_id)
            if initial_profile:
                for key, value in initial_profile.items():
                    if hasattr(profile, key):
                        setattr(profile, key, value)
            
            # 3. 保存到本地数据库
            self.user_manager.save_user_profile(profile)
            
            # 注意: 云端暂不支持用户画像写入，跳过远程同步
            logger.info(f"👤 初始化新用户: {user_id}")
        
        return profile
    
    async def update_user_info(self, user_id: str, new_info: Dict) -> bool:
        """更新用户信息
        
        记忆组件使用：
        - user_manager: 更新用户画像，保存更新洞察
        - remote_memory: 暂不使用（云端不支持用户画像更新）
        
        数据流：
        1. 更新本地用户画像 (user_manager)
        2. 保存更新洞察记录 (user_manager)
        """
        try:
            # 1. 更新本地用户画像
            success = self.user_manager.update_user_profile(user_id, new_info)
            
            if success:
                # 2. 保存更新洞察记录
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
        """保存对话记录
        
        这是核心方法，展示了三个记忆组件的协同工作：
        
        记忆组件使用：
        - llm: 智能分析对话上下文，提取用户画像信息
        - remote_memory: 存储原始对话内容到云端
        - user_manager: 存储结构化上下文、对话历史、用户画像更新、记忆洞察
        
        数据流：
        1. LLM分析 → 提取话题、意图、实体
        2. 远程存储 → 保存原始对话到MemOS
        3. 本地存储 → 更新对话上下文、历史记录
        4. 智能提取 → 从对话中提取用户画像信息
        5. 洞察保存 → 保存对话洞察用于模式分析
        
        容错设计：
        - 远程存储失败不影响本地保存
        - LLM分析失败使用默认值
        - 各步骤独立，互不影响
        """
        try:
            # ==================== 步骤1: LLM智能分析 ====================
            # 使用LLM分析对话，提取话题、意图、实体
            if not context:
                context = await self._analyze_conversation_context(message, response)
            
            # ==================== 步骤2: 远程记忆存储 ====================
            # 保存原始对话内容到远程MemOS（用于语义检索）
            try:
                messages_payload = [
                    {"role": "user", "content": str(message)},
                    {"role": "assistant", "content": str(response)}
                ]
                await self.remote_memory.save_conversation_memory(user_id, session_id, messages_payload)
            except Exception as e:
                logger.warning(f"⚠️ 远程记忆上传失败（不影响本地保存）: {e}")
            
            # ==================== 步骤3: 本地上下文更新 ====================
            # 获取或创建对话上下文
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
            
            # ==================== 步骤4: 分析结果更新 ====================
            # 将LLM分析结果更新到对话上下文
            if context:
                if context.get("topic"):
                    conv_context.current_topic = context["topic"]
                if context.get("intent"):
                    conv_context.user_intent = context["intent"]
                if context.get("entities"):
                    conv_context.mentioned_entities.extend(context["entities"])
                    # 去重并保留最近的
                    conv_context.mentioned_entities = list(set(conv_context.mentioned_entities))[-20:]
            
            # 保存对话上下文到本地数据库
            self.user_manager.save_conversation_context(conv_context)
            
            # ==================== 步骤5: 智能用户画像提取 ====================
            # 使用LLM从对话中提取用户画像信息
            await self._extract_user_profile_from_conversation(user_id, message, response)
            
            # ==================== 步骤6: 智能保存对话洞察（避免冗余） ====================
            # 优化：不是每次对话都保存洞察，而是基于条件智能保存
            should_save_insight = False
            save_reason = ""
            
            # 构建洞察数据
            insight_data = {
                "topic": context.get("topic", "未分类") if context else "未分类",
                "intent": context.get("intent", "") if context else "",
                "entities": context.get("entities", []) if context else [],
                "session_id": session_id,
                "timestamp": datetime.now().isoformat()
            }
            
            # 条件1: 话题有效且不是"未分类"
            if context and context.get("topic") and context.get("topic") != "未分类":
                # 检查最近的洞察，避免连续保存相同话题
                recent_insights = self.user_manager.get_memory_insights(user_id, insight_type="conversation", limit=1)
                if recent_insights:
                    last_topic = recent_insights[0].get('data', {}).get('topic', '')
                    if last_topic != context.get("topic"):
                        should_save_insight = True
                        save_reason = "话题变化"
                else:
                    # 第一条洞察
                    should_save_insight = True
                    save_reason = "首次洞察"
            
            # 条件2: 实体数量较多（说明对话信息丰富）
            if not should_save_insight and context and len(context.get("entities", [])) >= 3:
                should_save_insight = True
                save_reason = "信息丰富"
            
            # 条件3: 包含重要关键词（用户信息相关）
            important_keywords = ['我是', '我叫', '我的', '我想', '帮我', '提醒我']
            if not should_save_insight and any(keyword in message for keyword in important_keywords):
                should_save_insight = True
                save_reason = "重要对话"
            
            # 条件4: 每10次对话至少保存一次（防止完全不保存）
            if not should_save_insight:
                conversation_count = len(conv_context.conversation_history) if conv_context else 0
                if conversation_count % 10 == 0 and conversation_count > 0:
                    should_save_insight = True
                    save_reason = "定期保存"
            
            # 执行保存
            if should_save_insight:
                confidence = 0.8 if context and context.get("topic") and context.get("topic") != "未分类" else 0.5
                self.user_manager.save_memory_insight(
                    user_id,
                    "conversation",
                    insight_data,
                    confidence=confidence
                )
                logger.debug(f"💡 保存对话洞察: {insight_data.get('topic', '未知话题')} (原因: {save_reason})")
            else:
                logger.debug(f"⏭️  跳过洞察保存: {insight_data.get('topic', '未知话题')} (避免冗余)")
            
            logger.debug(f"💬 保存对话: {user_id} - {session_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 保存对话失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    async def get_user_context(self, user_id: str, session_id: str) -> Dict:
        """获取用户完整上下文
        
        这是记忆检索的核心方法，展示了三个记忆组件的协同工作：
        
        记忆组件使用：
        - user_manager: 获取用户画像、对话上下文、记忆洞察（本地快速访问）
        - remote_memory: 获取相关记忆（语义搜索，基于当前话题）
        - llm: 不直接使用，但为相关记忆提供语义理解基础
        
        数据流：
        1. 本地查询 → 用户画像、对话上下文、记忆洞察
        2. 远程检索 → 基于当前话题的相关记忆
        3. 数据整合 → 返回完整的用户上下文
        
        返回数据结构：
        {
            "user_profile": 用户画像信息,
            "conversation_context": 对话上下文,
            "relevant_memories": 相关记忆列表,
            "insights": 记忆洞察列表,
            "session_id": 会话ID
        }
        """
        try:
            # ==================== 步骤1: 本地数据查询 ====================
            # 获取用户画像（结构化数据，快速访问）
            profile = self.user_manager.get_user_profile(user_id)
            
            # 获取对话上下文（包含当前话题、意图、实体等）
            conv_context = self.user_manager.get_conversation_context(session_id)
            
            # ==================== 步骤2: 远程记忆检索 ====================
            # 基于当前话题获取相关记忆（语义搜索）
            recent_memories = await self.remote_memory.get_relevant_memories(
                user_id, 
                conv_context.current_topic if conv_context else "",
                session_id=session_id,
                context=""
            )
            
            # ==================== 步骤3: 记忆洞察查询 ====================
            # 获取用户行为洞察（模式分析结果）
            insights = self.user_manager.get_memory_insights(user_id, limit=5)
            
            # ==================== 步骤4: 数据整合 ====================
            # 整合所有记忆数据为统一上下文
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
    
    async def _analyze_conversation_context(self, message: str, response: str, max_retries: int = 2) -> Dict:
        """使用LLM分析对话上下文
        
        记忆组件使用：
        - llm: 智能分析对话，提取话题、意图、实体
        - user_manager: 不直接使用，但分析结果会保存到对话上下文
        
        功能：
        1. 使用LLM分析用户消息和助手回复
        2. 提取对话话题、用户意图、提及实体
        3. 返回结构化的分析结果
        
        返回格式：
        {
            "topic": "对话主题",
            "intent": "用户意图", 
            "entities": ["提及的实体列表"]
        }
        """
        for attempt in range(max_retries):
            try:
                analysis_prompt = f"""请分析以下对话，提取关键信息：

用户：{message}
助手：{response}

请以JSON格式返回分析结果（只返回JSON，不要其他内容）：
{{
    "topic": "对话主题",
    "intent": "用户意图",
    "entities": ["提及的实体（人名、地名、时间等）"]
}}"""
                
                messages = [Message(role=USER, content=analysis_prompt)]
                
                # 调用LLM分析
                analysis_result = ""
                for response_chunk in self.llm.chat(messages=messages):
                    if response_chunk:
                        analysis_result = response_chunk[-1].content
                
                # 解析JSON结果
                if analysis_result:
                    # 提取JSON部分（处理可能的markdown格式）
                    json_str = analysis_result.strip()
                    if "```json" in json_str:
                        json_str = json_str.split("```json")[1].split("```")[0].strip()
                    elif "```" in json_str:
                        json_str = json_str.split("```")[1].split("```")[0].strip()
                    
                    context = json.loads(json_str)
                    logger.debug(f"🧠 上下文分析成功: {context}")
                    return context
                
                logger.warning(f"⚠️ 上下文分析返回空结果 (尝试 {attempt + 1}/{max_retries})")
                
            except Exception as e:
                logger.warning(f"⚠️ 上下文分析失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    import asyncio
                    await asyncio.sleep(1)  # 重试前等待1秒
        
        logger.error(f"❌ 上下文分析最终失败，已重试{max_retries}次")
        return {}
    
    async def _extract_user_profile_from_conversation(self, user_id: str, message: str, response: str) -> bool:
        """从对话中智能提取用户画像信息
        
        记忆组件使用：
        - llm: 智能分析对话，提取用户个人信息
        - user_manager: 更新用户画像数据
        
        功能：
        1. 使用LLM从对话中提取用户个人信息
        2. 包括姓名、年龄、性别、位置、职业、兴趣等
        3. 自动更新用户画像到本地数据库
        
        提取字段：
        - name: 姓名
        - age: 年龄（数字）
        - gender: 性别
        - location: 当前位置或工作地点
        - home_address: 家庭住址
        - occupation: 职业
        - interests: 兴趣爱好（数组）
        - preferences: 偏好设置（对象）
        
        重要：只提取用户自己的信息，排除用户提到的其他人（如孩子、朋友、家人等）
        
        安全机制：
        1. 获取现有用户画像用于交叉验证
        2. 对于姓名字段，只有当对话中明确表达"我是XX"、"我的名字是XX"时才提取
        3. 如果提取的姓名与现有不一致且没有明确的第一人称表达，拒绝更新
        4. 过滤掉明显是其他人信息的字段
        """
        try:
            # ==================== 步骤1: 获取现有用户画像用于验证 ====================
            existing_profile = self.user_manager.get_user_profile(user_id)
            existing_name = existing_profile.name if existing_profile else None
            
            # ==================== 步骤2: 构建增强的提示词 ====================
            # 在提示词中包含现有信息，帮助LLM更好地判断
            existing_info_context = ""
            if existing_profile:
                existing_info_context = f"""
**重要：现有用户画像信息**（用于验证）：
- 现有姓名: {existing_name if existing_name else "未知"}
- 现有年龄: {existing_profile.age if existing_profile.age else "未知"}
- 现有性别: {existing_profile.gender if existing_profile.gender else "未知"}

**关键规则**：
1. 只有当对话中**明确使用第一人称**表达信息时，才能提取为用户本人信息
2. 姓名字段提取规则（最严格）：
   - ✅ 可以提取的情况："我是XX"、"我的名字是XX"、"我叫XX"、"我是XX，今年XX岁"
   - ❌ 禁止提取的情况："XX要参加"、"帮XX做"、"XX的XX"、"为XX安排"（这些明显是在说别人）
3. 如果提取的姓名与现有姓名不一致，且对话中没有第一人称表达，**必须返回空对象**
4. **绝对禁止**：将"XX要参加竞赛"、"帮XX添加待办"中的XX提取为用户自己的姓名
"""
            else:
                existing_info_context = """
**关键规则**：
1. 只有当对话中**明确使用第一人称**表达信息时，才能提取为用户本人信息
2. 姓名字段提取规则（最严格）：
   - ✅ 可以提取的情况："我是XX"、"我的名字是XX"、"我叫XX"、"我是XX，今年XX岁"
   - ❌ 禁止提取的情况："XX要参加"、"帮XX做"、"XX的XX"、"为XX安排"（这些明显是在说别人）
3. **绝对禁止**：将"帮XX添加待办"中的XX提取为用户自己的姓名
"""
            
            extract_prompt = f"""请从以下对话中提取**用户本人**的个人信息（如果有的话）：

用户：{message}
助手：{response}

{existing_info_context}

**提取规则**：
- **只提取用户自己的信息**，不要提取用户提到的其他人的信息
- **姓名提取最严格**：只有当用户明确说"我是XX"、"我的名字是XX"、"我叫XX"时才能提取
- 如果对话中只是提到要帮别人做什么、为别人安排什么、别人要参加什么，**这些都不是用户自己的信息**
- 对于"XX要参加"、"帮XX做"这类表达，XX一定是其他人，不是用户本人

请以JSON格式返回提取的信息（只返回JSON，不要其他内容）：
{{
    "name": "用户自己的姓名（必须对话中有'我是XX'、'我叫XX'等第一人称表达）",
    "age": "用户自己的年龄（数字，必须有'我今年XX岁'、'我是XX岁'等表达）",
    "gender": "用户自己的性别（必须有'我是男/女性'、'我是XX性'等表达）",
    "location": "用户自己的当前位置或工作地点",
    "home_address": "用户自己的家庭住址",
    "occupation": "用户的职业（必须有'我是XX'、'我从事XX'等表达）",
    "interests": ["用户自己的兴趣爱好（必须有'我喜欢XX'、'我爱好XX'等表达）"],
    "preferences": {{"用户自己的偏好设置（如语言偏好、沟通风格等）"}}
}}

注意：
- **如果没有提取到任何关于用户本人的明确信息，返回空对象 {{}}**
- **对于姓名、年龄、性别等关键字段，必须对话中有明确的第一人称表达，否则不要提取**
- **绝对不要将用户提到的其他人（如孩子、朋友、同事、家人）的信息误认为是用户自己的**
- 年龄必须是数字类型或null
- interests必须是数组格式或null
- preferences必须是对象格式或null
- 只提取明确提到的信息，不要推测
- 如果对话是"帮XX做XX"、"XX要参加XX"这类，说明XX是别人，不是用户本人"""
            
            messages = [Message(role=USER, content=extract_prompt)]
            
            # ==================== 步骤3: 调用LLM提取 ====================
            extract_result = ""
            for response_chunk in self.llm.chat(messages=messages):
                if response_chunk:
                    extract_result = response_chunk[-1].content
            
            # ==================== 步骤4: 解析和验证提取结果 ====================
            if extract_result:
                # 提取JSON部分
                json_str = extract_result.strip()
                if "```json" in json_str:
                    json_str = json_str.split("```json")[1].split("```")[0].strip()
                elif "```" in json_str:
                    json_str = json_str.split("```")[1].split("```")[0].strip()
                
                profile_info = json.loads(json_str)
                
                # ==================== 步骤5: 严格验证和过滤 ====================
                # 过滤空值
                profile_updates = {}
                for k, v in profile_info.items():
                    if v and v != "null" and v != "未提到":
                        # 对于姓名字段，进行额外的安全检查
                        if k == "name":
                            # 检查对话中是否有明确的第一人称表达（中文和英文）
                            first_person_indicators = [
                                "我是", "我叫", "我的名字是", "我姓", "我名", "本人是", "本人叫",
                                "i am", "i'm", "my name is", "i am called", "i go by"
                            ]
                            # 同时检查原始消息和转换为小写的消息（用于英文检测）
                            message_for_check = message + " " + message.lower()
                            
                            # 检查是否有第一人称表达
                            has_first_person = any(indicator in message_for_check for indicator in first_person_indicators)
                            
                            # 如果有现有姓名且不一致，需要第一人称表达才能更新
                            if existing_name and v != existing_name:
                                if not has_first_person:
                                    logger.warning(f"⚠️ 拒绝更新姓名：提取到 '{v}' 与现有姓名 '{existing_name}' 不一致，且对话中没有第一人称表达")
                                    continue
                                else:
                                    logger.info(f"✅ 允许更新姓名：有第一人称表达，从 '{existing_name}' 更新为 '{v}'")
                            # 如果没有现有姓名（首次设置），也需要第一人称表达才能设置（防止误提取他人姓名）
                            elif not existing_name:
                                if not has_first_person:
                                    logger.warning(f"⚠️ 拒绝设置姓名：提取到 '{v}' 但没有第一人称表达，可能是他人的姓名（如'XX要参加'中的XX）")
                                    continue
                                else:
                                    logger.info(f"✅ 允许设置姓名：有第一人称表达，设置姓名为 '{v}'")
                        
                        profile_updates[k] = v
                
                if profile_updates:
                    # 更新用户画像
                    success = self.user_manager.update_user_profile(user_id, profile_updates)
                    if success:
                        logger.info(f"👤 从对话中更新用户画像: {user_id} - {profile_updates}")
                    return success
            
            return False
            
        except Exception as e:
            logger.warning(f"⚠️ 提取用户画像失败: {e}")
            return False
    
    async def analyze_user_patterns(self, user_id: str) -> Dict:
        """分析用户模式
        
        记忆组件使用：
        - user_manager: 获取记忆洞察和用户画像，保存分析结果
        
        功能：
        1. 分析用户的历史对话洞察
        2. 统计常见话题和交互频率
        3. 生成用户行为模式分析
        4. 保存分析结果到记忆洞察
        
        分析内容：
        - interaction_frequency: 交互频率
        - common_topics: 常见话题统计
        - preferences: 用户偏好
        - behavioral_patterns: 行为模式
        """
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


# 全局集成记忆系统实例（延迟初始化）
integrated_memory = None

def get_integrated_memory():
    """获取集成记忆系统实例（单例模式）"""
    global integrated_memory
    if integrated_memory is None:
        integrated_memory = IntegratedMemorySystem()
    return integrated_memory


if __name__ == "__main__":
    # 测试代码
    import asyncio
    import os
    
    async def test_user_memory():
        from ty_mem_agent.utils.logger_config import get_logger
        test_logger = get_logger("UserMemoryTest")
        
        test_logger.info("="*50)
        test_logger.info("🧪 开始测试用户记忆系统")
        test_logger.info("="*50)
        
        # 检查API密钥配置
        from ty_mem_agent.config.settings import settings
        if not settings.DASHSCOPE_API_KEY or settings.DASHSCOPE_API_KEY == "your_dashscope_api_key_here":
            test_logger.error("❌ 请先在 ty_mem_agent/.env 中配置 DASHSCOPE_API_KEY")
            test_logger.info("💡 提示: 复制 env_example.txt 为 .env，然后填入你的API密钥")
            return
        
        system = IntegratedMemorySystem()
        
        # 测试1: 用户初始化（带初始画像）
        test_logger.info("\n📝 测试1: 用户初始化")
        profile = await system.initialize_user("zhang_san", {
            "name": "张三",
            "age": 28,
            "gender": "男",
            "location": "北京",
            "home_address": "北京市朝阳区",
            "interests": ["技术", "旅游"]
        })
        test_logger.info(f"✅ 初始用户画像: {asdict(profile)}")
        
        # 测试2: 对话保存（不提供context，让LLM分析）
        test_logger.info("\n📝 测试2: 保存对话并自动分析上下文")
        await system.save_conversation(
            "zhang_san",
            "session_001",
            "你好，我是张三，今年28岁，在阿里巴巴工作，家住北京市朝阳区，最近想去杭州旅游",
            "你好张三！很高兴认识你。杭州是个很美的城市，有西湖、灵隐寺等著名景点。作为技术人员，你也可以参观阿里巴巴西溪园区哦！"
        )
        test_logger.info("✅ 对话已保存并分析")
        
        # 测试3: 查看更新后的用户画像
        test_logger.info("\n📝 测试3: 查看智能更新后的用户画像")
        updated_profile = system.user_manager.get_user_profile("zhang_san")
        if updated_profile:
            test_logger.info(f"✅ 更新后画像:")
            test_logger.info(f"   - 姓名: {updated_profile.name}")
            test_logger.info(f"   - 年龄: {updated_profile.age}")
            test_logger.info(f"   - 性别: {updated_profile.gender}")
            test_logger.info(f"   - 位置: {updated_profile.location}")
            test_logger.info(f"   - 家庭住址: {updated_profile.home_address}")
            test_logger.info(f"   - 职业: {updated_profile.occupation}")
            test_logger.info(f"   - 兴趣: {updated_profile.interests}")
            test_logger.info(f"   - 偏好: {updated_profile.preferences}")
        
        # 测试4: 查看对话上下文
        test_logger.info("\n📝 测试4: 查看对话上下文")
        conv_context = system.user_manager.get_conversation_context("session_001")
        if conv_context:
            test_logger.info(f"✅ 对话上下文:")
            test_logger.info(f"   - 当前话题: {conv_context.current_topic}")
            test_logger.info(f"   - 用户意图: {conv_context.user_intent}")
            test_logger.info(f"   - 提及实体: {conv_context.mentioned_entities}")
            test_logger.info(f"   - 对话历史: {len(conv_context.conversation_history)} 条")
        
        # 测试5: 第二轮对话（测试更多字段提取）
        test_logger.info("\n📝 测试5: 第二轮对话（测试更多字段提取）")
        await system.save_conversation(
            "zhang_san",
            "session_001",
            "我是女性，喜欢音乐和摄影，平时比较喜欢安静的环境，今天杭州天气怎么样？",
            "杭州今天天气晴朗，温度22-28度，非常适合外出游玩。建议穿轻薄的衣服。音乐和摄影都是很棒的兴趣爱好，杭州有很多适合拍照的地方呢！"
        )
        
        # 测试6: 验证第二轮对话后的字段更新
        test_logger.info("\n📝 测试6: 验证第二轮对话后的字段更新")
        final_profile = system.user_manager.get_user_profile("zhang_san")
        if final_profile:
            test_logger.info(f"✅ 最终用户画像:")
            test_logger.info(f"   - 姓名: {final_profile.name}")
            test_logger.info(f"   - 年龄: {final_profile.age}")
            test_logger.info(f"   - 性别: {final_profile.gender}")
            test_logger.info(f"   - 位置: {final_profile.location}")
            test_logger.info(f"   - 家庭住址: {final_profile.home_address}")
            test_logger.info(f"   - 职业: {final_profile.occupation}")
            test_logger.info(f"   - 兴趣: {final_profile.interests}")
            test_logger.info(f"   - 偏好: {final_profile.preferences}")
        
        # 测试7: 获取完整用户上下文
        test_logger.info("\n📝 测试7: 获取完整用户上下文")
        full_context = await system.get_user_context("zhang_san", "session_001")
        test_logger.info(f"✅ 完整上下文包含:")
        test_logger.info(f"   - 用户画像字段: {full_context.get('user_profile', {})}")
        test_logger.info(f"   - 对话上下文字段: {full_context.get('conversation_context', {})}")
        test_logger.info(f"   - 相关记忆: {full_context.get('relevant_memories', [])} ")
        test_logger.info(f"   - 洞察数据: {full_context.get('insights', [])}")
        
        # 测试8: 分析用户模式
        test_logger.info("\n📝 测试8: 分析用户模式")
        patterns = await system.analyze_user_patterns("zhang_san")
        test_logger.info(f"✅ 用户模式分析:")
        test_logger.info(f"   - 交互频率: {patterns.get('interaction_frequency')}")
        test_logger.info(f"   - 常见话题: {patterns.get('common_topics')}")
        test_logger.info(f"   - 用户偏好: {patterns.get('preferences')}")
        
        test_logger.info("\n" + "="*50)
        test_logger.info("🎉 用户记忆系统测试完成！")
        test_logger.info("="*50)
    
    asyncio.run(test_user_memory())
