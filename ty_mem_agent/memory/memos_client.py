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
                "Authorization": f"Token {self.api_key}",
                "Content-Type": "application/json"
            },
            timeout=30.0
        )
    
    async def close(self):
        """关闭客户端"""
        await self.client.aclose()
    
    async def add_message(self,
                          user_id: str,
                          conversation_id: str,
                          messages: List[Dict[str, str]]) -> Dict:
        """云端：存储原始对话 /add/message"""
        try:
            payload = {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "messages": messages
            }
            response = await self.client.post("/add/message", json=payload)
            response.raise_for_status()
            result = response.json()
            logger.info(f"💾 上传对话成功: user={user_id}, conv={conversation_id}")
            return result
        except Exception as e:
            logger.error(f"❌ 上传对话失败: {e}")
            return {"error": str(e)}
    
    async def search_memory(self,
                            user_id: str,
                            conversation_id: str,
                            query: str,
                            memory_limit_number: Optional[int] = None) -> List[Dict]:
        """云端：检索相关记忆 /search/memory"""
        try:
            payload = {
                "query": query,
                "user_id": user_id,
                "conversation_id": conversation_id
            }
            if memory_limit_number is not None:
                payload["memory_limit_number"] = memory_limit_number
            response = await self.client.post("/search/memory", json=payload)
            response.raise_for_status()
            try:
                resp_json = response.json()
            except Exception:
                logger.error(f"❌ 检索记忆解析失败: 非JSON响应: {response.text}")
                return []
            if not isinstance(resp_json, dict):
                logger.error(f"❌ 检索记忆解析失败: 非对象JSON: {resp_json}")
                return []
            data = resp_json.get("data") or {}
            if not isinstance(data, dict):
                data = {}
            memories = data.get("memory_detail_list", []) or []
            try:
                logger.debug(f"🔎 search_memory payload: {json.dumps(payload, ensure_ascii=False)}")
                # 打印响应整体（截断）
                logger.debug(f"🔎 search_memory raw response: {json.dumps(resp_json, ensure_ascii=False)[:2000]}")
            except Exception:
                pass
            if memories:
                try:
                    preview = []
                    for m in memories[:5]:
                        preview.append({
                            "id": m.get("id"),
                            "memory_type": m.get("memory_type"),
                            "relativity": m.get("relativity"),
                            "memory_key": m.get("memory_key"),
                            "memory_value_preview": (m.get("memory_value", "")[:200])
                        })
                    logger.info(f"🧠 检索结果预览: {json.dumps(preview, ensure_ascii=False)}")
                except Exception:
                    pass
            logger.info(f"🔍 检索记忆: user={user_id}, conv={conversation_id}, 找到 {len(memories)} 条")
            return memories
        except httpx.TimeoutException as e:
            logger.error(f"❌ 检索记忆失败: 请求超时 ({self.api_base}/search/memory)")
            logger.debug(f"   超时详情: {e}")
            return []
        except httpx.ConnectError as e:
            logger.error(f"❌ 检索记忆失败: 无法连接到MemOS服务 ({self.api_base})")
            logger.debug(f"   连接错误: {e}")
            return []
        except httpx.HTTPStatusError as e:
            try:
                body = e.response.text if hasattr(e, 'response') and e.response else ""
            except Exception:
                body = ""
            status_code = e.response.status_code if hasattr(e, 'response') and e.response else "unknown"
            logger.error(f"❌ 检索记忆失败: HTTP错误 {status_code}")
            logger.debug(f"   错误详情: {e}; body={body[:500]}")
            return []
        except Exception as e:
            # 尝试获取响应体（如果存在）
            body = ""
            response_obj = None
            try:
                # 检查是否有response变量
                if 'response' in locals():
                    response_obj = response
                elif hasattr(e, 'response'):
                    response_obj = e.response
                if response_obj and hasattr(response_obj, 'text'):
                    body = response_obj.text[:500]
            except Exception:
                pass
            error_type = type(e).__name__
            logger.error(f"❌ 检索记忆失败: {error_type}: {e}")
            logger.debug(f"   错误详情: {e}; body={body}")
            logger.debug(f"   API地址: {self.api_base}/search/memory")
            logger.debug(f"   用户ID: {user_id}, 会话ID: {conversation_id}")
            return []
    
    async def get_messages(self,
                           user_id: str,
                           conversation_id: str,
                           message_limit_number: Optional[int] = 6) -> List[Dict]:
        """云端：获取消息 /get/message"""
        try:
            payload = {
                "user_id": user_id,
                "conversation_id": conversation_id
            }
            if message_limit_number is not None:
                payload["message_limit_number"] = message_limit_number
            response = await self.client.post("/get/message", json=payload)
            response.raise_for_status()
            try:
                resp_json = response.json()
            except Exception:
                logger.error(f"❌ 获取消息解析失败: 非JSON响应: {response.text}")
                return []
            if not isinstance(resp_json, dict):
                logger.error(f"❌ 获取消息解析失败: 非对象JSON: {resp_json}")
                return []
            data = resp_json.get("data") or {}
            if not isinstance(data, dict):
                data = {}
            messages = data.get("message_detail_list", []) or []
            logger.info(f"🗂️ 获取消息: user={user_id}, conv={conversation_id}, 条数={len(messages)}")
            return messages
        except Exception as e:
            try:
                body = response.text  # type: ignore
            except Exception:
                body = ""
            logger.error(f"❌ 获取消息失败: {e}; body={body}")
            return []
    
    # 以下旧接口占位（当前云端未开放）
    async def update_memory(self, memory_id: str, updates: Dict) -> Dict:
        return {"error": "not_supported_by_cloud_api"}
    async def delete_memory(self, memory_id: str) -> bool:
        return False
    
    async def get_memory_graph(self, user_id: str, depth: int = 2) -> Dict:
        logger.warning("get_memory_graph not supported by current cloud API, return empty.")
        return {"nodes": [], "edges": []}


class EnhancedMemoryManager:
    """增强记忆管理器
    
    结合MemOS和本地缓存，提供高效的记忆管理
    """
    
    def __init__(self):
        self.memos_client = MemOSClient()
        self.local_cache = {}  # 本地缓存
        self.cache_timeout = 300  # 5分钟缓存
        self.max_cache_size = 10000  # 最大缓存条目数
    
    async def close(self):
        """关闭管理器"""
        await self.memos_client.close()
    
    def _get_cache_key(self, user_id: str, query: str, session_id: str = None) -> str:
        """生成缓存键 - 基于用户ID和查询内容，不依赖易变的context"""
        # 使用稳定哈希，避免 Python 内置 hash 的随机盐影响
        import hashlib
        normalized = (query or "").lower().strip().encode('utf-8')
        query_hash = hashlib.sha256(normalized).hexdigest()[:16]
        session_part = f":{session_id}" if session_id else ""
        return f"memory:{user_id}:{query_hash}{session_part}"
    
    def _is_cache_valid(self, cache_entry: Dict) -> bool:
        """检查缓存是否有效"""
        if not cache_entry:
            return False
        
        cache_time = cache_entry.get("timestamp", 0)
        return (datetime.now().timestamp() - cache_time) < self.cache_timeout
    
    def _cleanup_cache(self):
        """清理过期缓存，防止内存泄漏"""
        current_time = datetime.now().timestamp()
        expired_keys = []
        
        for key, entry in self.local_cache.items():
            if (current_time - entry.get("timestamp", 0)) > self.cache_timeout:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self.local_cache[key]
        
        # 如果缓存仍然过大，删除最旧的条目
        if len(self.local_cache) > self.max_cache_size:
            sorted_items = sorted(
                self.local_cache.items(), 
                key=lambda x: x[1].get("timestamp", 0)
            )
            # 删除最旧的20%条目
            to_remove = int(self.max_cache_size * 0.2)
            for key, _ in sorted_items[:to_remove]:
                del self.local_cache[key]
        
        logger.debug(f"🧹 缓存清理完成，当前缓存条目: {len(self.local_cache)}")
    
    async def save_user_profile(self, user_id: str, profile: Dict) -> Dict:
        logger.warning("save_user_profile not supported by current cloud API.")
        return {"error": "not_supported_by_cloud_api"}
    
    async def save_conversation_memory(self, user_id: str, session_id: str, messages: List[Dict[str, str]]) -> Dict:
        """保存对话到云端（原始消息列表）"""
        return await self.memos_client.add_message(
            user_id=user_id,
            conversation_id=session_id,
            messages=messages
        )
    
    async def get_session_memories(self, user_id: str, session_id: str, limit: int = 10) -> List[Dict]:
        """获取特定会话的记忆"""
        try:
            # 使用云端获取消息接口
            messages = await self.memos_client.get_messages(
                user_id=user_id,
                conversation_id=session_id,
                message_limit_number=limit
            )
            return messages
            
        except Exception as e:
            logger.error(f"❌ 获取会话记忆失败: {e}")
            return []
    
    async def save_knowledge(self, content: str, domain: str = "general", tags: List[str] = None) -> Dict:
        logger.warning("save_knowledge not supported by current cloud API.")
        return {"error": "not_supported_by_cloud_api"}
    
    async def get_relevant_memories(self, user_id: str, query: str, session_id: str = None, context: str = "") -> List[Dict]:
        """获取相关记忆（带智能缓存）
        
        Args:
            user_id: 用户ID
            query: 查询内容
            session_id: 会话ID（可选，用于会话级别的缓存）
            context: 上下文信息（用于会话记忆检索，不影响缓存键）
        """
        # 生成缓存键（不依赖易变的context）
        cache_key = self._get_cache_key(user_id, query, session_id)
        
        # 检查缓存
        if cache_key in self.local_cache and self._is_cache_valid(self.local_cache[cache_key]):
            logger.info(f"📋 使用缓存记忆: key={cache_key}, size={len(self.local_cache[cache_key]['data'])}")
            return self.local_cache[cache_key]["data"]
        
        # 定期清理缓存
        if len(self.local_cache) > self.max_cache_size * 0.8:
            self._cleanup_cache()
        
        # 从MemOS检索
        memories = []
        
        # 云端基于会话的相关记忆检索
        conv_id = session_id or "default"
        session_memories = await self.memos_client.search_memory(
            user_id=user_id,
            conversation_id=conv_id,
            query=query or (context or "")
        )
        memories.extend(session_memories)
        
        # 缓存结果
        self.local_cache[cache_key] = {
            "data": memories,
            "timestamp": datetime.now().timestamp()
        }
        logger.debug(f"💾 写入缓存: key={cache_key}, size={len(memories)}")
        logger.debug(f"💾 缓存记忆: {cache_key}, 记忆数量: {len(memories)}")
        return memories
    
    async def update_user_context(self, user_id: str, new_info: Dict) -> None:
        logger.warning("update_user_context not supported by current cloud API.")
    
    async def get_user_profile(self, user_id: str) -> Dict:
        logger.warning("get_user_profile not supported by current cloud API.")
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
            # 测试对话记忆（带session_id，按云端原始消息格式）
            session_id = "session_001"
            messages_payload = [
                {"role": "user", "content": "我想了解北京今天的天气"},
                {"role": "assistant", "content": "今天北京晴朗，最高温度28℃"}
            ]
            # await manager.save_conversation_memory(
            #     "test_user",
            #     session_id,
            #     messages_payload
            # )
            
            # 测试记忆检索（第一次，会查询数据库）
            test_logger.info("🔍 第一次查询...")
            memories1 = await manager.get_relevant_memories("test_user", "喜欢吃什么", session_id)
            test_logger.info(f"找到 {len(memories1)} 条相关记忆")
            
            # 测试记忆检索（第二次，应该使用缓存）
            test_logger.info("🔍 第二次查询（应该使用缓存）...")
            memories2 = await manager.get_relevant_memories("test_user", "天气", session_id)
            test_logger.info(f"找到 {len(memories2)} 条相关记忆")
            
            # 测试不同context的查询（不影响缓存键）
            test_logger.info("🔍 不同context的查询...")
            memories3 = await manager.get_relevant_memories("test_user", "天气", session_id, context="今天很冷")
            test_logger.info(f"找到 {len(memories3)} 条相关记忆")
            
            # 测试会话记忆
            session_memories = await manager.get_session_memories("test_user", session_id)
            test_logger.info(f"会话记忆: {len(session_memories)} 条")
            test_logger.info(f"会话记忆: {session_memories}")
            
        finally:
            await manager.close()
    
    asyncio.run(test_memory_system())
