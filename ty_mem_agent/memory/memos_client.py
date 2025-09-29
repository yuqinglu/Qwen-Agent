#!/usr/bin/env python3
"""
MemOS记忆系统客户端
集成 https://memos.openmem.net/ 的记忆管理平台
"""

import asyncio
import json
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
import httpx
from loguru import logger

# 使用简洁的绝对导入
from ty_mem_agent.config.settings import settings


class MemoryType:
    """记忆类型常量"""
    PARAMETER = "parameter"  # 参数记忆
    ACTIVATION = "activation"  # 激活记忆
    PLAINTEXT = "plaintext"  # 明文记忆


class MemoryScope:
    """记忆范围常量"""
    USER = "user"  # 用户个人记忆
    GENERAL = "general"  # 通用知识记忆
    SESSION = "session"  # 会话记忆


class MemOSClient:
    """MemOS API客户端"""
    
    def __init__(self, api_base: str = None, api_key: str = None):
        self.api_base = api_base or settings.MEMOS_API_BASE
        self.api_key = api_key or settings.MEMOS_API_KEY
        self.client = httpx.AsyncClient(
            base_url=self.api_base,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            timeout=30.0
        )
    
    async def close(self):
        """关闭客户端"""
        await self.client.aclose()
    
    async def save_memory(self, 
                         user_id: str,
                         content: Union[str, Dict],
                         memory_type: str = MemoryType.PLAINTEXT,
                         scope: str = MemoryScope.USER,
                         tags: List[str] = None,
                         metadata: Dict = None) -> Dict:
        """保存记忆"""
        try:
            memory_data = {
                "user_id": user_id,
                "content": content if isinstance(content, str) else json.dumps(content),
                "memory_type": memory_type,
                "scope": scope,
                "tags": tags or [],
                "metadata": metadata or {},
                "timestamp": datetime.now().isoformat(),
                "ttl": settings.MEMORY_RETENTION_DAYS * 24 * 3600  # 保存天数
            }
            
            response = await self.client.post("/api/v1/memories", json=memory_data)
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"💾 保存记忆成功: user={user_id}, type={memory_type}, id={result.get('memory_id')}")
            return result
            
        except Exception as e:
            logger.error(f"❌ 保存记忆失败: {e}")
            return {"error": str(e)}
    
    async def retrieve_memories(self,
                              user_id: str,
                              query: str = None,
                              memory_type: str = None,
                              scope: str = None,
                              tags: List[str] = None,
                              limit: int = 10) -> List[Dict]:
        """检索记忆"""
        try:
            params = {
                "user_id": user_id,
                "limit": limit
            }
            
            if query:
                params["query"] = query
            if memory_type:
                params["memory_type"] = memory_type
            if scope:
                params["scope"] = scope
            if tags:
                params["tags"] = ",".join(tags)
            
            response = await self.client.get("/api/v1/memories/search", params=params)
            response.raise_for_status()
            
            memories = response.json().get("memories", [])
            logger.info(f"🔍 检索记忆: user={user_id}, 找到 {len(memories)} 条记忆")
            return memories
            
        except Exception as e:
            logger.error(f"❌ 检索记忆失败: {e}")
            return []
    
    async def update_memory(self, memory_id: str, updates: Dict) -> Dict:
        """更新记忆"""
        try:
            response = await self.client.patch(f"/api/v1/memories/{memory_id}", json=updates)
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"🔄 更新记忆成功: id={memory_id}")
            return result
            
        except Exception as e:
            logger.error(f"❌ 更新记忆失败: {e}")
            return {"error": str(e)}
    
    async def delete_memory(self, memory_id: str) -> bool:
        """删除记忆"""
        try:
            response = await self.client.delete(f"/api/v1/memories/{memory_id}")
            response.raise_for_status()
            
            logger.info(f"🗑️ 删除记忆成功: id={memory_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 删除记忆失败: {e}")
            return False
    
    async def get_memory_graph(self, user_id: str, depth: int = 2) -> Dict:
        """获取记忆图谱"""
        try:
            params = {"user_id": user_id, "depth": depth}
            response = await self.client.get("/api/v1/memories/graph", params=params)
            response.raise_for_status()
            
            graph = response.json()
            logger.info(f"🕸️ 获取记忆图谱: user={user_id}, 节点数={len(graph.get('nodes', []))}")
            return graph
            
        except Exception as e:
            logger.error(f"❌ 获取记忆图谱失败: {e}")
            return {"nodes": [], "edges": []}


class EnhancedMemoryManager:
    """增强记忆管理器
    
    结合MemOS和本地缓存，提供高效的记忆管理
    """
    
    def __init__(self):
        self.memos_client = MemOSClient()
        self.local_cache = {}  # 本地缓存
        self.cache_timeout = 300  # 5分钟缓存
    
    async def close(self):
        """关闭管理器"""
        await self.memos_client.close()
    
    def _get_cache_key(self, user_id: str, context: str) -> str:
        """生成缓存键"""
        return f"memory:{user_id}:{hash(context)}"
    
    def _is_cache_valid(self, cache_entry: Dict) -> bool:
        """检查缓存是否有效"""
        if not cache_entry:
            return False
        
        cache_time = cache_entry.get("timestamp", 0)
        return (datetime.now().timestamp() - cache_time) < self.cache_timeout
    
    async def save_user_profile(self, user_id: str, profile: Dict) -> Dict:
        """保存用户画像"""
        return await self.memos_client.save_memory(
            user_id=user_id,
            content=profile,
            memory_type=MemoryType.PARAMETER,
            scope=MemoryScope.USER,
            tags=["profile", "personal"],
            metadata={"category": "user_profile"}
        )
    
    async def save_conversation_memory(self, user_id: str, conversation: str, context: Dict = None) -> Dict:
        """保存对话记忆"""
        return await self.memos_client.save_memory(
            user_id=user_id,
            content=conversation,
            memory_type=MemoryType.PLAINTEXT,
            scope=MemoryScope.SESSION,
            tags=["conversation", "dialogue"],
            metadata=context or {}
        )
    
    async def save_knowledge(self, content: str, domain: str = "general", tags: List[str] = None) -> Dict:
        """保存通用知识"""
        return await self.memos_client.save_memory(
            user_id="system",
            content=content,
            memory_type=MemoryType.PLAINTEXT,
            scope=MemoryScope.GENERAL,
            tags=tags or [domain, "knowledge"],
            metadata={"domain": domain}
        )
    
    async def get_relevant_memories(self, user_id: str, query: str, context: str = "") -> List[Dict]:
        """获取相关记忆（带缓存）"""
        cache_key = self._get_cache_key(user_id, f"{query}:{context}")
        
        # 检查缓存
        if cache_key in self.local_cache and self._is_cache_valid(self.local_cache[cache_key]):
            logger.debug(f"📋 使用缓存记忆: {cache_key}")
            return self.local_cache[cache_key]["data"]
        
        # 从MemOS检索
        memories = []
        
        # 1. 检索用户个人记忆
        user_memories = await self.memos_client.retrieve_memories(
            user_id=user_id,
            query=query,
            scope=MemoryScope.USER,
            limit=5
        )
        memories.extend(user_memories)
        
        # 2. 检索通用知识
        general_memories = await self.memos_client.retrieve_memories(
            user_id="system",
            query=query,
            scope=MemoryScope.GENERAL,
            limit=3
        )
        memories.extend(general_memories)
        
        # 3. 检索会话记忆
        if context:
            session_memories = await self.memos_client.retrieve_memories(
                user_id=user_id,
                query=context,
                scope=MemoryScope.SESSION,
                limit=2
            )
            memories.extend(session_memories)
        
        # 缓存结果
        self.local_cache[cache_key] = {
            "data": memories,
            "timestamp": datetime.now().timestamp()
        }
        
        return memories
    
    async def update_user_context(self, user_id: str, new_info: Dict) -> None:
        """更新用户上下文信息"""
        try:
            # 获取现有用户画像
            profile_memories = await self.memos_client.retrieve_memories(
                user_id=user_id,
                scope=MemoryScope.USER,
                tags=["profile"],
                limit=1
            )
            
            if profile_memories:
                # 更新现有画像
                memory_id = profile_memories[0]["memory_id"]
                current_profile = json.loads(profile_memories[0]["content"])
                current_profile.update(new_info)
                
                await self.memos_client.update_memory(
                    memory_id,
                    {"content": json.dumps(current_profile)}
                )
            else:
                # 创建新画像
                await self.save_user_profile(user_id, new_info)
                
            logger.info(f"🔄 更新用户上下文: user={user_id}")
            
        except Exception as e:
            logger.error(f"❌ 更新用户上下文失败: {e}")
    
    async def get_user_profile(self, user_id: str) -> Dict:
        """获取用户画像"""
        try:
            memories = await self.memos_client.retrieve_memories(
                user_id=user_id,
                scope=MemoryScope.USER,
                tags=["profile"],
                limit=1
            )
            
            if memories:
                return json.loads(memories[0]["content"])
            else:
                return {}
                
        except Exception as e:
            logger.error(f"❌ 获取用户画像失败: {e}")
            return {}


# 全局记忆管理器实例
memory_manager = EnhancedMemoryManager()


async def cleanup_memory_manager():
    """清理记忆管理器"""
    await memory_manager.close()


if __name__ == "__main__":
    # 测试代码
    async def test_memory_system():
        from ty_mem_agent.utils.logger_config import get_logger
        test_logger = get_logger("MemosClientTest")
        
        manager = EnhancedMemoryManager()
        
        try:
            # 测试用户画像
            await manager.save_user_profile("test_user", {
                "name": "张三",
                "age": 28,
                "city": "北京",
                "interests": ["科技", "旅行", "美食"]
            })
            
            # 测试对话记忆
            await manager.save_conversation_memory(
                "test_user",
                "用户询问了北京今天的天气情况",
                {"topic": "weather", "location": "北京"}
            )
            
            # 测试记忆检索
            memories = await manager.get_relevant_memories("test_user", "天气")
            test_logger.info(f"🔍 找到 {len(memories)} 条相关记忆")
            
        finally:
            await manager.close()
    
    asyncio.run(test_memory_system())
