#!/usr/bin/env python3
"""
TY Memory Agent - 基于QwenAgent的智能记忆代理
直接集成QwenAgent内置工具，简洁高效
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from dataclasses import asdict
from loguru import logger

# 添加QwenAgent路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    from qwen_agent.agents.assistant import Assistant
    from qwen_agent.llm import get_chat_model
    from qwen_agent.llm.schema import Message, USER, SYSTEM
    from qwen_agent.tools.base import BaseTool
    logger.info("✅ 成功导入QwenAgent核心组件")
except ImportError as e:
    logger.error(f"❌ 无法导入QwenAgent核心组件: {e}")
    raise

# 本地导入
from ty_mem_agent.config.settings import get_llm_config
from ty_mem_agent.memory.user_memory import get_integrated_memory


class TYMemoryAgent(Assistant):
    """TY个人智能助理 - 基于QwenAgent Assistant
    
    特性：
    - 个人助理定位：在保护隐私前提下提供贴心服务
    - 记忆管理：记住用户信息、偏好、待办事项
    - 智能工具：查询天气、规划行程等实用功能
    - 多用户支持：为不同用户提供个性化服务
    - 隐私保护：严格保护用户个人信息安全
    """
    
    def __init__(self, 
                 function_list: Optional[List[Union[str, Dict, BaseTool]]] = None,
                 llm: Optional[Union[Dict, Any]] = None,
                 system_message: Optional[str] = None,
                 name: Optional[str] = "TY个人智能助理",
                 description: Optional[str] = None,
                 **kwargs):
        
        # 默认系统消息
        if not system_message:
            system_message = self._build_system_message()
        
        if not description:
            description = ("个人智能助理，在保护用户隐私的前提下，"
                          "帮助用户记住待办事项、个人信息及偏好，"
                          "具备智能工具调用能力，可查询天气、规划行程等")
        
        # 默认LLM配置
        if llm is None:
            llm_config = get_llm_config()
            logger.info("=" * 50)
            logger.info("🔑 TYMemoryAgent 使用的API Key信息")
            logger.info("=" * 50)
            logger.info(f"模型类型: {llm_config.get('model_type', 'unknown')}")
            logger.info(f"模型名称: {llm_config.get('model', 'unknown')}")
            logger.info(f"API Key: {llm_config.get('api_key', 'None')[:10]}...")
            if 'model_server' in llm_config:
                logger.info(f"模型服务器: {llm_config.get('model_server', 'None')}")
            logger.info("=" * 50)
            llm = get_chat_model(llm_config)
        
        # 默认工具列表 - 使用QwenAgent内置工具和自定义工具
        if function_list is None:
            function_list = self._get_default_tools()
        
        # 初始化父类
        super().__init__(
            function_list=function_list,
            llm=llm,
            system_message=system_message,
            name=name,
            description=description,
            **kwargs
        )
        
        # 初始化集成记忆系统（包含了memory_manager）
        self.integrated_memory = get_integrated_memory()
        
        # 用户上下文
        self.current_user_id: Optional[str] = None
        self.current_session_id: Optional[str] = None
        
        logger.info(f"✅ 成功创建TY记忆智能代理: {self.name}")
        logger.info(f"✅ 可用工具: {list(self.function_map.keys())}")
    
    def _build_system_message(self) -> str:
        """构建系统消息"""
        return """你是一个个人智能助理，在保护用户隐私的前提下，为用户提供贴心服务：

🧠 记忆管理：
- 记住用户的个人信息、偏好和习惯
- 管理用户的待办事项和重要提醒
- 维护对话上下文，提供连贯的交互体验
- 为不同用户提供个性化服务

📝 待办管理：
- 智能识别用户提到的待办事项，自动提取时间、地点、人物、事件等信息
- 当用户说"帮我记个待办"、"添加待办"时，使用extract_todo工具创建待办
- 当用户询问"我今天有什么事"、"明天的日程"时，使用query_todos工具查询
- 主动检测时间冲突，提醒用户待办安排
- 支持待办的完成、删除、修改等操作
- 重要：调用待办工具时，必须使用用户的真实user_id（不是用户名或显示名称）

🔄 待办更新识别：
- 当用户说"补充一下"、"对了"、"还有"、"修改"、"更新"等词语时，通常是在更新刚创建的待办
- 如果对话历史中有刚创建的待办，用户补充信息时应该调用update_todo工具更新
- 更新场景示例：
  * "对了，地点是XX" → 更新location字段
  * "补充一下，时间是XX" → 更新deadline字段  
  * "还有，参与人包括XX" → 更新participants字段
  * "修改一下，改成XX" → 更新相应字段

📋 待办ID获取：
- 更新待办时，必须使用正确的todo_id
- 如果对话历史中刚创建了待办，从工具调用结果中获取返回的todo_id
- 如果无法确定待办ID，先调用query_todos工具查询用户的待办列表
- 不要使用硬编码的ID（如1、2等），必须使用实际的待办ID

🛠️ 智能工具：
- 查询天气信息，为用户出行提供参考
- 规划行程路线，优化出行方案
- 查询时间和日期，支持不同时区和格式
- 管理待办事项，智能提醒和冲突检测
- 调用其他实用工具，满足用户日常需求

💡 服务原则：
- 严格保护用户隐私，不泄露个人信息
- 主动利用记忆信息提供个性化服务
- 根据用户偏好调整服务风格和内容
- 及时调用工具满足用户实际需求
- 主动提醒待办事项和时间冲突
- 保持友好、专业、贴心的服务态度

请根据用户的需求和记忆信息，提供最合适的个人助理服务。"""
    
    def _get_default_tools(self) -> List[Union[str, Dict, BaseTool]]:
        """获取默认工具列表（从工具注册中心获取）"""
        try:
            from ty_mem_agent.mcp_integrations import get_tool_registry
            
            # 从工具注册中心获取所有已初始化的工具
            registry = get_tool_registry()
            tools = registry.get_all_tools()
            
            if tools:
                logger.debug(f"✅ Agent 从工具注册中心获取到 {len(tools)} 个工具")
                
                # 打印工具摘要
                tool_names = [getattr(t, 'name', 'unknown') for t in tools]
                logger.debug(f"   工具列表: {', '.join(tool_names)}")
            else:
                logger.warning("⚠️ 工具注册中心未返回任何工具")
            
            return tools
            
        except Exception as e:
            logger.error(f"❌ 从工具注册中心获取工具失败: {e}")
            logger.error("   Agent 将在没有工具的情况下运行")
            return []
    
    async def run_with_memory(self, 
                       messages: List[Any], 
                       user_id: str = "default_user",
                       session_id: str = "default_session",
                       **kwargs):
        """带记忆的对话运行（异步）"""
        try:
            # 提取用户的原始query
            user_query = ""
            for msg in messages:
                if msg.role == USER and isinstance(msg.content, str):
                    user_query = msg.content
                    break
            
            # 获取用户记忆（传入用户原始query）
            user_memory = await self._get_user_memory(user_id, session_id, user_query)
            logger.debug(f"🔍 获取用户记忆: {user_memory}")
            
            # 构建带记忆的消息
            enhanced_messages = self._enhance_messages_with_memory(messages, user_memory, user_id)
            logger.debug(f"🔍 构建带记忆的消息: {enhanced_messages}")
            
            # 记录发送给LLM的完整提示词
            logger.info("=" * 80)
            logger.info("📝 发送给LLM的完整提示词:")
            logger.info("=" * 80)
            for i, msg in enumerate(enhanced_messages):
                logger.info(f"消息 {i+1} [{msg.role}]:")
                logger.info(f"{msg.content}")
                logger.info("-" * 40)
            logger.info("=" * 80)
            
            # 运行对话
            logger.info("🔍 开始调用LLM...")
            logger.info(f"🔍 当前LLM配置: {getattr(self.llm, '__class__', 'Unknown')}")
            logger.info(f"🔍 LLM类型: {type(self.llm)}")
            
            response = []
            for chunk in self.run(messages=enhanced_messages, **kwargs):
                response = chunk
                yield chunk
            
            # 更新用户记忆（异步）
            await self._update_user_memory(user_id, session_id, messages, response)
            
        except Exception as e:
            logger.error(f"❌ 带记忆对话运行失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # 回退到普通对话
            for chunk in self.run(messages=messages, **kwargs):
                yield chunk
    
    async def _get_user_memory(self, user_id: str, session_id: str, user_query: str = "") -> Dict[str, Any]:
        """获取用户记忆（结合本地和远程记忆）
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
            user_query: 用户的原始查询内容
        """
        try:
            # 1. 获取用户基本信息（本地）
            user_profile = self.integrated_memory.user_manager.get_user_profile(user_id)
            
            # 2. 获取对话上下文（本地）
            conversation_context = self.integrated_memory.user_manager.get_conversation_context(session_id)
            
            # 3. 提取最近的对话历史（本地）
            conversation_history = []
            if conversation_context and conversation_context.conversation_history:
                conversation_history = conversation_context.conversation_history[-5:]  # 最近5条
            
            # 4. 获取相关记忆（远程 + 本地缓存）
            relevant_memories = []
            try:
                # 构建查询：结合用户原始query和提取的topic
                # 优先使用用户原始query，如果topic存在则追加作为补充
                query_parts = []
                
                if user_query:
                    query_parts.append(user_query)
                
                # 如果有提取的topic，作为补充信息
                if conversation_context and conversation_context.current_topic:
                    # 避免重复：只有当topic不在用户query中时才添加
                    if conversation_context.current_topic not in user_query:
                        query_parts.append(conversation_context.current_topic)
                
                # 组合查询字符串
                combined_query = " ".join(query_parts) if query_parts else ""
                
                logger.debug(f"🔍 组合查询: user_query='{user_query}', topic='{conversation_context.current_topic if conversation_context else ''}', combined='{combined_query}'")
                
                # 使用组合查询获取相关记忆
                if combined_query:
                    relevant_memories = await self.integrated_memory.remote_memory.get_relevant_memories(
                        user_id, 
                        combined_query,
                        session_id=session_id,
                        context=""
                    )
                    logger.debug(f"🔍 获取到 {len(relevant_memories)} 条相关记忆")
                else:
                    logger.debug("🔍 没有有效的查询内容，跳过远程记忆检索")
                    
            except Exception as e:
                logger.warning(f"⚠️ 获取相关记忆失败: {e}")
                relevant_memories = []
            
            # 5. 获取记忆洞察（本地）
            insights = self.integrated_memory.user_manager.get_memory_insights(user_id, limit=5)
            
            return {
                "user_profile": user_profile,
                "conversation_history": conversation_history,
                "conversation_context": conversation_context,
                "relevant_memories": relevant_memories,  # 新增：相关记忆
                "insights": insights,  # 新增：记忆洞察
                "session_id": session_id
            }
        except Exception as e:
            logger.warning(f"⚠️ 获取用户记忆失败: {e}")
            return {}
    
    def _enhance_messages_with_memory(self, messages: List[Message], user_memory: Dict[str, Any], user_id: str = None) -> List[Message]:
        """用记忆增强消息"""
        try:
            enhanced_messages = messages.copy()
            
            # 添加用户记忆信息到第一条消息
            if enhanced_messages and user_memory:
                memory_context = self._format_memory_context(user_memory, user_id)
                if memory_context:
                    # 在第一条消息前添加记忆上下文
                    memory_message = Message(
                        role=SYSTEM,
                        content=f"用户记忆信息：\n{memory_context}"
                    )
                    enhanced_messages.insert(0, memory_message)
            
            return enhanced_messages
        except Exception as e:
            logger.warning(f"⚠️ 记忆增强失败: {e}")
            return messages
    
    def _format_memory_context(self, user_memory: Dict[str, Any], user_id: str = None) -> str:
        """格式化记忆上下文"""
        try:
            context_parts = []
            
            # 1. 用户基本信息
            user_profile = user_memory.get("user_profile", {})
            if user_profile:
                profile_info = []
                if hasattr(user_profile, 'user_id') and user_profile.user_id:
                    profile_info.append(f"用户ID: {user_profile.user_id}")
                if hasattr(user_profile, 'name') and user_profile.name:
                    profile_info.append(f"姓名: {user_profile.name}")
                if hasattr(user_profile, 'age') and user_profile.age:
                    profile_info.append(f"年龄: {user_profile.age}")
                if hasattr(user_profile, 'location') and user_profile.location:
                    profile_info.append(f"位置: {user_profile.location}")
                if hasattr(user_profile, 'occupation') and user_profile.occupation:
                    profile_info.append(f"职业: {user_profile.occupation}")
                if hasattr(user_profile, 'interests') and user_profile.interests:
                    profile_info.append(f"兴趣: {', '.join(user_profile.interests)}")
                if profile_info:
                    context_parts.append(f"用户画像: {'; '.join(profile_info)}")
            elif user_id:
                context_parts.append(f"用户ID: {user_id}")
            
            # 2. 对话历史
            conversation_history = user_memory.get("conversation_history", [])
            if conversation_history:
                recent_topics = []
                for conv in conversation_history[-3:]:  # 最近3条对话
                    if isinstance(conv, dict) and conv.get('context', {}).get('topic'):
                        recent_topics.append(conv['context']['topic'])
                if recent_topics:
                    context_parts.append(f"最近话题: {', '.join(recent_topics)}")
            
            # 3. 相关记忆（新增）
            relevant_memories = user_memory.get("relevant_memories", [])
            if relevant_memories:
                memory_summaries = []
                for memory in relevant_memories[:5]:  # 最多5条相关记忆
                    if isinstance(memory, dict):
                        # 从MemOS返回的记忆使用memory_value和memory_key字段
                        memory_key = memory.get('memory_key', '')
                        memory_value = memory.get('memory_value', memory.get('content', ''))
                        
                        if memory_value:
                            # 格式化记忆内容
                            memory_text = f"{memory_key}: {memory_value}" if memory_key else memory_value
                            # 截断过长的内容
                            if len(memory_text) > 150:
                                memory_text = memory_text[:150] + "..."
                            memory_summaries.append(memory_text)
                
                if memory_summaries:
                    context_parts.append(f"\n相关历史记忆:\n" + "\n".join([f"- {m}" for m in memory_summaries]))
            
            # 4. 记忆洞察（新增）
            insights = user_memory.get("insights", [])
            if insights:
                insight_types = [insight.get('type', '') for insight in insights if isinstance(insight, dict)]
                if insight_types:
                    context_parts.append(f"用户洞察: {', '.join(set(insight_types))}")
            
            return "\n".join(context_parts) if context_parts else ""
        except Exception as e:
            logger.warning(f"⚠️ 格式化记忆上下文失败: {e}")
            return ""
    
    async def _update_user_memory(self, 
                           user_id: str, 
                           session_id: str, 
                           messages: List[Message], 
                           response: List[Message]):
        """更新用户记忆"""
        try:
            # 提取最后一条用户消息和助手回复
            user_message = ""
            assistant_response = ""
            
            for msg in messages:
                if isinstance(msg, Message) and msg.role == USER:
                    user_message = msg.content if isinstance(msg.content, str) else str(msg.content)
            
            if response and len(response) > 0:
                last_response = response[-1]
                if isinstance(last_response, Message):
                    assistant_response = last_response.content if isinstance(last_response.content, str) else str(last_response.content)
            
            # 保存对话到记忆系统
            if user_message and assistant_response:
                await self.integrated_memory.save_conversation(
                    user_id, session_id, user_message, assistant_response
            )
            
            # 分析并更新用户偏好
            self._analyze_user_preferences(user_id, messages, response)
            
        except Exception as e:
            logger.warning(f"⚠️ 更新用户记忆失败: {e}")
    
    def _analyze_user_preferences(self, 
                                 user_id: str, 
                                 messages: List[Message], 
                                 response: List[Message]):
        """分析用户偏好"""
        try:
            # 简单的偏好分析逻辑
            # 实际应用中可以使用更复杂的NLP分析
            
            # 检查是否使用了工具
            tool_usage = []
            for msg in response:
                if isinstance(msg, Message) and msg.function_call:
                    tool_usage.append(msg.function_call.name)
            
            if tool_usage:
                # 更新用户工具使用偏好
                # 使用user_manager的update_user_profile方法
                preferences_update = {
                    "preferences": {
                        "preferred_tools": tool_usage,
                        "last_tool_usage": tool_usage[-1] if tool_usage else None
                    }
                }
                self.integrated_memory.user_manager.update_user_profile(
                    user_id, preferences_update
                )
                logger.debug(f"📊 更新用户工具偏好: {user_id} - {tool_usage}")
                
        except Exception as e:
            logger.warning(f"⚠️ 分析用户偏好失败: {e}")
    
    async def set_user_context(self, user_id: str, session_id: str):
        """设置用户上下文"""
        self.current_user_id = user_id
        self.current_session_id = session_id
        logger.info(f"📝 设置用户上下文: user={user_id}, session={session_id}")
    
    async def get_user_summary(self, user_id: str) -> Dict[str, Any]:
        """获取用户摘要"""
        try:
            # 获取用户画像
            profile = self.integrated_memory.user_manager.get_user_profile(user_id)
            
            # 获取最近的记忆洞察
            insights = self.integrated_memory.user_manager.get_memory_insights(user_id, limit=5)
            
            # 统计信息
            conversation_insights = [i for i in insights if i["type"] == "conversation"]
            
            return {
                "user_profile": asdict(profile) if profile else {},
                "total_insights": len(insights),
                "conversation_count": len(conversation_insights),
                "recent_insights": insights
            }
        except Exception as e:
            logger.error(f"❌ 获取用户摘要失败: {e}")
            return {}
    
    async def cleanup(self):
        """清理资源"""
        try:
            logger.info(f"🧹 清理Agent资源: user={self.current_user_id}")
            self.current_user_id = None
            self.current_session_id = None
        except Exception as e:
            logger.error(f"❌ Agent清理失败: {e}")


if __name__ == "__main__":
    # 测试TY记忆智能代理
    import asyncio
    from ty_mem_agent.utils.logger_config import get_logger
    test_logger = get_logger("TYMemoryAgentTest")
    
    async def test_ty_memory_agent():
        """异步测试函数"""
        test_logger.info("🧪 测试TY记忆智能代理...")
        
        try:
            # 创建代理实例
            agent = TYMemoryAgent()
            test_logger.info(f"✅ 代理创建成功: {agent.name}")
            test_logger.info(f"✅ 代理描述: {agent.description}")
            test_logger.info(f"✅ 可用工具: {list(agent.function_map.keys())}")
            
            # 设置用户上下文
            await agent.set_user_context("zhang_san", "test_session")
            test_logger.info("✅ 用户上下文已设置")
            
            # 测试带记忆的对话
            test_messages = [
                Message(role=USER, content="你好，我是张三，我想了解一下今天北京的天气")
            ]
            
            test_logger.info("🎯 测试带记忆的对话...")
            response_count = 0
            async for response in agent.run_with_memory(
                messages=test_messages,
                user_id="zhang_san",
                session_id="test_session"
            ):
                response_count += 1
                if response and len(response) > 0:
                    test_logger.info(f"📝 响应 #{response_count}: {response[-1].content[:100]}...")
            
            test_logger.info(f"✅ 收到 {response_count} 个响应块")
            
            # 测试获取用户摘要
            test_logger.info("🎯 测试获取用户摘要...")
            summary = await agent.get_user_summary("zhang_san")
            test_logger.info(f"✅ 用户摘要: {summary}")
            
            # 测试清理
            test_logger.info("🎯 测试资源清理...")
            await agent.cleanup()
            test_logger.info("✅ 资源清理完成")
            
            test_logger.info("🎉 TY记忆智能代理测试完成！")
            
        except Exception as e:
            test_logger.error(f"❌ 测试失败: {e}")
            import traceback
            traceback.print_exc()
    
    # 运行异步测试
    asyncio.run(test_ty_memory_agent())
