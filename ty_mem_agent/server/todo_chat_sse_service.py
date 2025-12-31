#!/usr/bin/env python3
"""
待办聊天SSE流式服务
实现基于ReAct的AI对话，并通过SSE流式返回处理过程
"""

import json
import uuid
import asyncio
from datetime import datetime
from typing import AsyncIterator, Dict, List, Optional, Any
from loguru import logger

from .todo_chat_manager import get_todo_chat_manager, TodoChatSession
from ty_mem_agent.agents.todo_chat_agent import get_todo_chat_agent
from qwen_agent.llm.schema import Message, USER


class ExecutionStep:
    """执行步骤"""
    def __init__(self, step_id: int, step_type: str, desc: str):
        self.id = step_id
        self.type = step_type  # analysis, tool, update, generate
        self.desc = desc
        self.status = "pending"  # pending, running, completed, failed
        self.progress = 0.0
        self.error = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "type": self.type,
            "desc": self.desc,
            "status": self.status,
            "progress": self.progress,
            "error": self.error
        }
    
    def update_status(self, status: str, desc: Optional[str] = None, progress: Optional[float] = None):
        """更新步骤状态"""
        self.status = status
        if desc:
            self.desc = desc
        if progress is not None:
            self.progress = progress


class TodoChatSSEService:
    """待办聊天SSE流式服务"""
    
    def __init__(self):
        self.chat_manager = get_todo_chat_manager()
        self.agent = get_todo_chat_agent()
    
    async def process_message_stream(
        self,
        event_id: int,
        user_id: int,
        content: str,
        session_id: Optional[str] = None,
        title: Optional[str] = None,
        todo_content: Optional[str] = None,
        rich_cards: Optional[List[Dict]] = None
    ) -> AsyncIterator[str]:
        """
        处理用户消息并流式返回结果
        
        Args:
            event_id: 待办事件ID
            user_id: 用户ID
            content: 用户消息内容
            session_id: 会话ID（为空则创建新会话）
            title: 会话标题（仅创建新会话时有效）
            todo_content: 当前待办内容
            rich_cards: 当前富媒体卡片列表
            
        Yields:
            SSE格式的事件流
        """
        start_time = datetime.now()
        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        full_message_content = ""  # 完整的AI回复内容
        new_todo_content = None
        new_rich_cards = []
        suggestions = []
        
        try:
            # ========== 阶段 1: 会话初始化 ==========
            session = await self._init_session(
                event_id, user_id, session_id, title, 
                todo_content, rich_cards
            )
            
            # 推送会话初始化事件
            yield self._format_sse_event("session_init", {
                "session_id": session.session_id,
                "event_id": event_id,
                "created_at": session.created_at,
                "is_new": session_id is None
            })
            
            # 保存用户消息
            self.chat_manager.add_message(
                session.session_id,
                role="user",
                content=content
            )
            
            # ========== 阶段 2: 快速意图分析 ==========
            analysis_result = await self._analyze_intent(
                content, todo_content, rich_cards, session.messages
            )
            
            # 确保analysis_result不为None
            if analysis_result is None:
                logger.error("❌ 意图分析返回None，使用默认值")
                analysis_result = {
                    "summary": "分析用户需求",
                    "need_tools": True,
                    "need_update_todo": False,
                    "need_suggestions": False,
                    "change_summary": None
                }
            
            # 生成执行计划
            steps = self._create_dynamic_plan(analysis_result)
            yield self._format_sse_event("plan_update", {
                "steps": [step.to_dict() for step in steps]
            })
            
            await asyncio.sleep(0.1)
            
            # ========== 阶段 3: AI推理与执行（ReAct） ==========
            # 更新执行步骤为"运行中"
            if len(steps) > 0:
                steps[0].update_status("running", desc="AI正在分析并制定方案...", progress=0.1)
                yield self._format_sse_event("plan_update", {
                    "steps": [step.to_dict() for step in steps]
                })
            
            # 准备历史消息
            history = []
            for msg in session.messages[-10:]:  # 只取最近10条
                # msg是ChatMessage对象，不是字典
                history.append({
                    "role": msg.role if hasattr(msg, 'role') else "user",
                    "content": msg.content if hasattr(msg, 'content') else ""
                })
            
            # 调用Agent进行推理和执行（实时监控和推送）
            logger.info(f"🤖 开始AI推理: user_message={content[:50]}...")
            agent_response = None
            
            async for event in self._run_agent_with_monitoring(
                user_message=content,
                todo_content=todo_content,
                rich_cards=rich_cards,
                history=history,
                steps=steps
            ):
                # 区分SSE事件和最终响应
                if isinstance(event, dict) and event.get("_type") == "final_response":
                    # 最终响应
                    agent_response = event["response"]
                else:
                    # SSE事件，转发给前端
                    yield event
            
            # 确保获取到了响应
            if agent_response is None:
                raise ValueError("Agent未返回响应")
            
            # 更新第一步为完成
            if len(steps) > 0:
                steps[0].update_status("completed", desc="AI分析完成", progress=1.0)
                yield self._format_sse_event("plan_update", {
                    "steps": [step.to_dict() for step in steps]
                })
            
            # ========== 阶段 4: 解析AI响应 ==========
            logger.info(f"📝 解析AI响应，长度: {len(agent_response)}")
            logger.debug(f"📝 完整响应内容:\n{agent_response}...")  # 输出前500字符用于调试
            parsed = self.agent.parse_response(agent_response)
            
            full_message_content = parsed.get("content", "")
            new_todo_content = parsed.get("todo_content")
            new_rich_cards = parsed.get("rich_cards", [])
            suggestions = parsed.get("suggested_todos", [])
            
            logger.info(f"✅ 解析完成: 回复={len(full_message_content)}字, 待办={'是' if new_todo_content else '否'}, 卡片={len(new_rich_cards)}个, 建议={len(suggestions)}个")
            if full_message_content:
                logger.debug(f"📝 解析后的回复内容: {full_message_content[:200]}...")
            else:
                logger.warning("⚠️ 解析后的回复内容为空！")
            
            # ========== 阶段 5: 推送富媒体卡片 ==========
            if new_rich_cards:
                if len(steps) > 1:
                    steps[1].update_status("running", desc="正在推送富媒体卡片...", progress=0.3)
                    yield self._format_sse_event("plan_update", {
                        "steps": [step.to_dict() for step in steps]
                    })
                
                for i, card in enumerate(new_rich_cards, 1):
                    # 确保卡片有card_id
                    if "card_id" not in card:
                        card["card_id"] = f"card_{uuid.uuid4().hex[:8]}"
                    yield self._format_sse_event("rich_card", card)
                    
                    # 更新进度
                    if len(steps) > 1:
                        progress = 0.3 + (0.7 * i / len(new_rich_cards))
                        steps[1].update_status("running", desc=f"正在推送富媒体卡片 {i}/{len(new_rich_cards)}...", progress=progress)
                        yield self._format_sse_event("plan_update", {
                            "steps": [step.to_dict() for step in steps]
                        })
                    
                    await asyncio.sleep(0.1)
                
                if len(steps) > 1:
                    steps[1].update_status("completed", desc=f"已推送{len(new_rich_cards)}个富媒体卡片", progress=1.0)
                    yield self._format_sse_event("plan_update", {
                        "steps": [step.to_dict() for step in steps]
                    })
            
            # ========== 阶段 6: 推送待办内容更新 ==========
            if new_todo_content:
                step_idx = 2 if len(steps) > 2 else 1
                if len(steps) > step_idx:
                    steps[step_idx].update_status("running", desc="正在更新待办内容...", progress=0.5)
                    yield self._format_sse_event("plan_update", {
                        "steps": [step.to_dict() for step in steps]
                    })
                
                yield self._format_sse_event("todo_update", {
                    "base_version": 1,
                    "new_version": 2,
                    "change_summary": analysis_result.get("change_summary", "AI已更新待办内容"),
                    "new_content": new_todo_content
                })
                
                if len(steps) > step_idx:
                    steps[step_idx].update_status("completed", desc="待办内容已更新", progress=1.0)
                    yield self._format_sse_event("plan_update", {
                        "steps": [step.to_dict() for step in steps]
                    })
            
            # ========== 阶段 7: 推送AI回复 ==========
            # 直接一次性推送完整回复内容，无需逐字推送
            if full_message_content:
                yield self._format_sse_event("message_delta", {"content": full_message_content})
            
            # ========== 阶段 8: 推送建议待办 ==========
            if suggestions:
                logger.info(f"💡 推送{len(suggestions)}个待办建议")
                yield self._format_sse_event("suggestions", suggestions)
            
            # ========== 阶段 8: 保存并完成 ==========
            # 保存AI生成的富媒体卡片到RichCardManager
            if new_rich_cards:
                from ty_mem_agent.server.rich_card_manager import get_rich_card_manager
                card_manager = get_rich_card_manager()
                for card_data in new_rich_cards:
                    try:
                        # 使用已有的card_id（如果存在），否则由RichCardManager生成
                        card_id = card_data.get("card_id")
                        card_manager.create_card(
                            event_id=event_id,
                            user_id=user_id,
                            card_type=card_data.get("card_type", "custom"),
                            title=card_data.get("title", "未命名卡片"),
                            subtitle=card_data.get("subtitle"),
                            icon=card_data.get("icon"),
                            data=card_data.get("data", {}),
                            source=card_data.get("source"),
                            expires_at=card_data.get("expires_at"),
                            card_id=card_id
                        )
                    except Exception as e:
                        logger.warning(f"⚠️ 保存富媒体卡片失败: {e}")
            
            # 保存AI回复消息
            self.chat_manager.add_message(
                session.session_id,
                role="assistant",
                content=full_message_content,
                todo_content=new_todo_content,
                suggested_todos=suggestions,
                rich_cards=new_rich_cards
            )
            
            # 更新会话上下文
            if new_todo_content:
                self.chat_manager.update_session_context(
                    session.session_id,
                    todo_content=new_todo_content,
                    rich_cards=new_rich_cards
                )
            
            # 推送完成事件
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            
            # 尝试从agent获取token使用量（如果可用）
            token_usage = {
                "input_tokens": len(content) // 2,  # 粗略估算
                "output_tokens": len(full_message_content) // 2,  # 粗略估算
                "total_tokens": (len(content) + len(full_message_content)) // 2
            }
            
            yield self._format_sse_event("done", {
                "message_id": message_id,
                "session_id": session.session_id,
                "usage": token_usage,
                "duration_ms": duration_ms
            })
            
            logger.info(f"✅ 待办聊天处理完成: session={session.session_id}, duration={duration_ms}ms")
            
        except Exception as e:
            logger.error(f"❌ 待办聊天处理失败: {e}", exc_info=True)
            yield self._format_sse_event("error", {
                "code": 500,
                "message": "处理失败",
                "detail": str(e),
                "recoverable": True
            })
            yield self._format_sse_event("done", {
                "message_id": None,
                "error": True
            })
    
    async def _init_session(
        self,
        event_id: int,
        user_id: int,
        session_id: Optional[str],
        title: Optional[str],
        todo_content: Optional[str],
        rich_cards: Optional[List[Dict]]
    ) -> TodoChatSession:
        """初始化或获取会话"""
        if session_id:
            session = self.chat_manager.get_session(session_id)
            if session:
                return session
            else:
                logger.warning(f"⚠️ 会话不存在，创建新会话: {session_id}")
        
        # 创建新会话
        return self.chat_manager.create_session(
            event_id=event_id,
            user_id=user_id,
            title=title or "新对话",
            todo_content=todo_content,
            rich_cards=rich_cards
        )
    
    def _create_dynamic_plan(self, analysis_result: Dict[str, Any]) -> List[ExecutionStep]:
        """根据意图分析动态创建执行计划"""
        steps = [
            ExecutionStep(1, "analysis", "AI推理与方案制定")
        ]
        
        step_id = 2
        if analysis_result.get("need_tools"):
            steps.append(ExecutionStep(step_id, "tool", "查询相关服务并生成富媒体卡片"))
            step_id += 1
        
        if analysis_result.get("need_update_todo"):
            steps.append(ExecutionStep(step_id, "update", "更新待办内容"))
            step_id += 1
        
        steps.append(ExecutionStep(step_id, "generate", "生成回复"))
        
        return steps
    
    async def _run_agent_with_monitoring(
        self,
        user_message: str,
        todo_content: Optional[str],
        rich_cards: Optional[List[Dict]],
        history: List[Dict],
        steps: List[ExecutionStep]
    ):
        """
        运行Agent并实时监控执行过程（异步生成器）
        
        使用ReAct agent进行推理，自动调用工具和生成响应
        实时监控工具调用，立即解析和推送结果
        
        Yields:
            - SSE事件字典（用于推送给前端）
            - 最终响应字典（包含_type="final_response"）
        """
        try:
            # 构建消息上下文
            messages = self.agent._build_context_messages(
                user_message=user_message,
                todo_content=todo_content,
                rich_cards=rich_cards,
                history=history
            )
            
            # 运行ReAct推理，实时监控
            full_response = ""
            logger.info("🤖 开始ReAct推理...")
            
            previous_response = ""
            tool_call_count = 0
            pushed_thoughts = set()  # 记录已经推送过的Thought内容（使用hash避免重复）
            
            # 调用agent的_run方法（生成器，会在每次工具调用时yield）
            for response in self.agent._run(messages, lang='zh'):
                if response and len(response) > 0:
                    current_response = response[-1].content
                    full_response = current_response
                    
                    # 提取并推送新的Thought内容（如果有）
                    if len(current_response) > len(previous_response):
                        new_thought, thought_hash = self._extract_latest_thought(current_response, previous_response, pushed_thoughts)
                        if new_thought:
                            # 推送Thought内容，使用chain_of_thought事件类型，与最终的message_delta区分
                            # 通过hash去重，确保相同的Thought不会被重复推送
                            yield self._format_sse_event("chain_of_thought", {"content": new_thought})
                            # 记录已推送的Thought（使用内容的hash）
                            pushed_thoughts.add(thought_hash)
                            await asyncio.sleep(0.05)  # 短暂延迟，让前端能渲染
                    
                    # 检测是否有新的工具调用
                    if "Action:" in current_response and "Observation:" in current_response:
                        # 提取工具调用信息
                        if len(current_response) > len(previous_response):
                            new_content = current_response[len(previous_response):]
                            
                            # 检查是否包含新的Observation（表示工具调用完成）
                            if "Observation:" in new_content:
                                tool_call_count += 1
                                
                                # 提取Action和Observation
                                action_match = self._extract_action(current_response)
                                observation_match = self._extract_last_observation(current_response)
                                
                                if action_match and observation_match:
                                    tool_name, tool_input = action_match
                                    observation = observation_match
                                    
                                    logger.info(f"🔧 工具调用 #{tool_call_count}: {tool_name}")
                                    logger.info(f"   输入: {tool_input[:100]}...")
                                    logger.info(f"   输出: {observation[:100]}...")
                                    
                                    # 实时推送：工具调用状态更新
                                    if len(steps) > 1:
                                        # 计算进度：基于工具调用次数
                                        progress = min(0.3 + (0.6 * tool_call_count / max(tool_call_count, 1)), 0.9)
                                        steps[1].update_status("running", desc=f"正在调用工具：{tool_name}...", progress=progress)
                                        yield self._format_sse_event("plan_update", {
                                            "steps": [step.to_dict() for step in steps]
                                        })
                                        await asyncio.sleep(0.05)  # 短暂延迟，让前端能渲染
                                        
                                        # 工具调用完成，解析结果
                                        progress = min(0.3 + (0.6 * (tool_call_count + 0.5) / max(tool_call_count, 1)), 0.95)
                                        steps[1].update_status("running", desc=f"工具调用完成：{tool_name}，正在处理结果...", progress=progress)
                                        yield self._format_sse_event("plan_update", {
                                            "steps": [step.to_dict() for step in steps]
                                        })
                                    
                    
                    previous_response = current_response
                    
                    # 调试日志
                    if len(full_response) % 200 == 0:  # 每200字符记录一次
                        logger.debug(f"ReAct进度: {len(full_response)}字符...")
            
            logger.info(f"✅ ReAct推理完成，响应长度: {len(full_response)}，工具调用: {tool_call_count}次")
            
            # 最终完成，更新步骤1状态
            if len(steps) > 1:
                steps[1].update_status("completed", desc=f"AI推理完成（{tool_call_count}次工具调用）", progress=1.0)
                yield self._format_sse_event("plan_update", {
                    "steps": [step.to_dict() for step in steps]
                })
            
            # 返回最终响应（特殊格式）
            yield {
                "_type": "final_response",
                "response": full_response
            }
            
        except Exception as e:
            logger.error(f"❌ Agent执行失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            # 推送错误事件
            yield self._format_sse_event("error", {
                "code": 500,
                "message": f"AI推理失败: {str(e)}",
                "recoverable": False
            })
            
            # 返回错误响应
            yield {
                "_type": "final_response",
                "response": f"抱歉，处理您的请求时遇到了问题。错误信息：{str(e)}"
            }
    
    def _extract_action(self, text: str) -> Optional[tuple]:
        """提取最后一次Action和Action Input"""
        import re
        # 查找最后一个Action和Action Input
        action_pattern = r'Action:\s*([^\n]+)\s*\nAction Input:\s*(.*?)(?=\nObservation:|$)'
        matches = list(re.finditer(action_pattern, text, re.DOTALL))
        if matches:
            last_match = matches[-1]
            tool_name = last_match.group(1).strip()
            tool_input = last_match.group(2).strip()
            return (tool_name, tool_input)
        return None
    
    def _extract_last_observation(self, text: str) -> Optional[str]:
        """提取最后一次Observation"""
        import re
        # 查找最后一个Observation
        obs_pattern = r'Observation:\s*(.*?)(?=\nThought:|$)'
        matches = list(re.finditer(obs_pattern, text, re.DOTALL))
        if matches:
            return matches[-1].group(1).strip()
        return None
    
    def _extract_latest_thought(self, current_response: str, previous_response: str, pushed_thoughts: set) -> tuple:
        """
        提取最新的Thought内容
        
        Args:
            current_response: 当前的完整响应内容
            previous_response: 上一次的响应内容（用于对比，找出新的Thought）
            pushed_thoughts: 已推送Thought的hash集合（避免重复推送）
            
        Returns:
            (清理后的Thought内容, thought_hash)，如果没有新Thought或已推送过则返回(None, None)
        """
        import re
        import hashlib
        
        try:
            # 提取所有Thought
            thought_pattern = r'Thought:\s*(.*?)(?=\n(?:Action:|Observation:|Final Answer:|Thought:|$))'
            all_thoughts = list(re.finditer(thought_pattern, current_response, re.DOTALL | re.IGNORECASE))
            
            if not all_thoughts:
                return None, None
            
            # 从后往前查找，找出新的Thought（不在previous_response中的）
            for thought_match in reversed(all_thoughts):
                thought_content = thought_match.group(1).strip()
                
                # 检查这个Thought是否在previous_response中（说明已经推送过）
                if previous_response and thought_match.group(0) in previous_response:
                    continue
                
                # 检查这个Thought是否已经推送过（通过hash）
                thought_hash = hashlib.md5(thought_content.encode()).hexdigest()
                if thought_hash in pushed_thoughts:
                    continue
                
                # 清理Thought内容：移除过多的技术细节，保留用户友好的部分
                # 限制长度，避免太长的Thought影响体验
                clean_thought = thought_content
                if len(clean_thought) > 200:
                    # 尝试提取关键信息（开头部分通常最重要）
                    clean_thought = clean_thought[:200] + "..."
                
                # 移除一些过于技术性的表述，使其更友好
                # 例如："我需要使用工具" -> "正在查询相关信息"
                clean_thought = clean_thought.replace("我需要使用", "正在")
                clean_thought = clean_thought.replace("我将", "正在")
                
                return clean_thought, thought_hash
            
            return None, None
            
        except Exception as e:
            logger.debug(f"提取Thought失败: {e}")
            return None, None
    
    async def _try_parse_and_push_cards(self, observation: str):
        """
        尝试从observation中解析富媒体卡片（异步生成器）
        
        工具返回的结果可能包含JSON格式的数据，尝试解析为卡片
        
        Yields:
            rich_card SSE事件
        """
        import re
        import json
        
        try:
            # 尝试查找JSON内容
            json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
            matches = re.findall(json_pattern, observation)
            
            for match in matches:
                try:
                    data = json.loads(match)
                    
                    # 检查是否像是一个卡片数据
                    if isinstance(data, dict) and any(key in data for key in ['weather', 'temperature', 'city', 'location', 'name', 'address', 'price']):
                        # 构建简单的卡片
                        card = {
                            "card_id": f"card_{uuid.uuid4().hex[:8]}",
                            "card_type": self._infer_card_type(data),
                            "title": self._infer_card_title(data),
                            "data": data,
                            "source": "工具调用",
                            "updated_at": datetime.now().isoformat()
                        }
                        
                        logger.info(f"🎴 从工具结果中解析出卡片（类型: {card['card_type']}），立即推送")
                        yield self._format_sse_event("rich_card", card)
                        await asyncio.sleep(0.05)  # 短暂延迟
                        
                except json.JSONDecodeError:
                    continue
                    
        except Exception as e:
            logger.debug(f"解析卡片失败（正常，不是所有工具都返回卡片）: {e}")
    
    def _infer_card_type(self, data: dict) -> str:
        """根据数据内容推断卡片类型"""
        if any(k in data for k in ['weather', 'temperature']):
            return 'weather'
        elif any(k in data for k in ['route', 'distance', 'duration']):
            return 'navigation'
        elif any(k in data for k in ['hotel', 'room', 'price']):
            return 'hotel'
        elif any(k in data for k in ['flight', 'airline', 'departure']):
            return 'flight'
        else:
            return 'info'
    
    def _infer_card_title(self, data: dict) -> str:
        """根据数据内容推断卡片标题"""
        if 'city' in data:
            return f"{data['city']}天气"
        elif 'name' in data:
            return data['name']
        elif 'title' in data:
            return data['title']
        else:
            return "查询结果"
    
    async def _analyze_intent(
        self,
        content: str,
        todo_content: Optional[str],
        rich_cards: Optional[List[Dict]],
        history_messages: List
    ) -> Dict[str, Any]:
        """
        分析用户意图，制定执行计划
        
        使用AI快速分析用户需求，判断需要执行的操作
        利用已有的富媒体卡片信息，避免重复查询，提供更智能的分析
        """
        try:
            # 构建历史对话上下文
            history_context = ""
            if history_messages and len(history_messages) > 0:
                # 只取最近5轮对话，避免提示词过长
                recent_messages = history_messages[-5:]
                history_lines = []
                for msg in recent_messages:
                    # msg可能是ChatMessage对象或字典，需要兼容处理
                    if hasattr(msg, 'role'):
                        # ChatMessage对象
                        role = msg.role
                        msg_content = msg.content if hasattr(msg, 'content') else ''
                    else:
                        # 字典
                        role = msg.get('role', 'user')
                        msg_content = msg.get('content', '')
                    
                    if role == 'user':
                        history_lines.append(f"用户: {msg_content}")
                    elif role == 'assistant':
                        # 助手消息可能很长，只取前100字
                        short_content = msg_content[:100] + "..." if len(msg_content) > 100 else msg_content
                        history_lines.append(f"助手: {short_content}")
                
                history_context = f"""
历史对话记录（最近{len(recent_messages)}轮）:
{chr(10).join(history_lines)}

注意：用户当前的消息可能是基于历史对话的，请结合上下文理解用户意图。
"""
            
            # 构建富媒体卡片上下文
            cards_context = ""
            if rich_cards and len(rich_cards) > 0:
                # 不做简化，直接使用完整的卡片信息
                # 卡片本身就是精简且必要的信息，应该完整传递给AI
                cards_json = json.dumps(rich_cards, ensure_ascii=False, indent=2)
                
                cards_context = f"""
已有的富媒体卡片（之前已查询的信息）:
```json
{cards_json}
```

注意：
1. 如果用户询问的信息已在上述卡片中，无需重复查询，可以直接引用卡片内容回答
2. 请仔细检查卡片的具体数据，判断是否完全满足用户当前的需求
3. 如果卡片信息已过时（如查询时间较早）或用户明确要求更新，则需要重新查询
4. 如果用户基于已有卡片提出新的需求，应该充分利用卡片中的详细信息进行分析
"""
            
            # 构建详细的分析提示词
            analysis_prompt = f"""你是一个智能待办助手的任务规划器，需要深入分析用户需求并制定执行计划。

## 📋 任务背景

用户正在使用待办管理系统，你需要帮助用户完成待办相关的任务。你的职责是：
1. 理解用户的真实意图（不仅是字面意思）
2. 分析需要执行哪些操作
3. 充分利用已有的信息，避免重复工作
4. 主动思考用户可能需要但没有明说的帮助

## 📊 当前上下文信息
{history_context}
### 当前用户消息
{content}

### 当前待办内容
{todo_content or '（用户暂未创建待办内容）'}
{cards_context}

## 🎯 分析要点

### 1. 深入理解用户意图
- **字面意思**：用户明确说了什么？
- **隐含意图**：用户可能想要什么但没有明说？
- **上下文关联**：结合历史对话，用户真正的目的是什么？
- **指代关系**：用户说的"查一下"、"更新"、"那个"指的是什么？

### 2. 智能利用已有信息
- **富媒体卡片**：
  - 检查卡片中是否已有用户需要的信息
  - 卡片数据是否完整、准确、及时？
  - 用户是否明确要求更新（"刷新"、"重新查询"、"最新"）？
  - 如果卡片信息充分且及时，应该设置 need_tools=false
  
- **历史对话**：
  - 用户之前讨论过什么？
  - 当前消息是延续之前的话题还是新的需求？
  - 用户的表达是否依赖之前的上下文？

### 3. 判断需要执行的操作

#### need_tools（是否需要调用外部工具/MCP）
**设为 true 的情况：**
- 用户明确要求查询信息（天气、导航、酒店等）
- 富媒体卡片中没有相关信息
- 卡片信息已过时或用户明确要求更新
- 需要创建日程/提醒等操作

**设为 false 的情况：**
- 富媒体卡片中已有完整、准确、及时的信息
- 用户只是询问卡片中已有的数据
- 用户只是要求更新待办文本，不涉及外部查询

#### need_update_todo（是否需要更新待办内容）
**设为 true 的情况：**
- 用户明确要求"补充"、"完善"、"修改"、"添加"待办内容
- 用户提供了新的信息需要加入待办（如地点、时间、人员等）
- 查询到的信息需要记录到待办中（如天气情况、路线信息等）
- 待办内容需要细化、分解或重新组织

**设为 false 的情况：**
- 用户只是询问信息，不需要修改待办
- 用户只是查询某个数据，不需要记录
- 当前待办已经很完整，无需补充

#### need_suggestions（是否需要生成建议待办）
**设为 true 的情况：**
- 用户明确要求"建议"、"推荐"相关任务
- 当前待办是复杂任务，可以拆解为子任务
- 当前待办需要前置准备工作（如"开会"需要"准备材料"）
- 当前待办完成后有后续任务（如"出差"后有"报销"）
- 基于待办内容，主动发现用户可能遗漏的相关任务

**设为 false 的情况：**
- 用户只是简单的信息查询
- 待办任务已经很简单明确
- 用户没有表现出需要帮助规划的意图

## 💡 分析示例

### 示例1：信息查询
用户："明天天气怎么样？"
富媒体卡片：已有明天的天气卡片（查询时间：今天上午）
分析：
- 意图：查询明天天气
- 卡片中已有信息且较新
- 不需要重新查询工具
- 结果：need_tools=false, need_update_todo=false, need_suggestions=false

### 示例2：待办完善
用户："帮我加上会议地点和参会人员"
分析：
- 意图：完善待办内容
- 需要更新待办文本
- 可能需要建议相关准备工作（如"预约会议室"）
- 结果：need_tools=false, need_update_todo=true, need_suggestions=true

### 示例3：综合任务
用户："明天去北京出差，帮我规划一下"
分析：
- 意图：出差规划（复杂任务）
- 需要查询天气、交通等信息
- 需要更新待办内容，添加详细计划
- 需要建议相关准备任务（订票、订酒店、准备材料等）
- 结果：need_tools=true, need_update_todo=true, need_suggestions=true

## 📤 输出要求

请用JSON格式回复，包含以下字段：
{{
    "summary": "对用户意图的深入理解和分析（2-3句话，说明你理解到了什么）",
    "need_tools": true/false,
    "need_update_todo": true/false,
    "need_suggestions": true/false,
    "change_summary": "如果需要更新待办，简要说明会做哪些更新（如果不需要则为null）",
    "reasoning": "你的分析推理过程（1-2句话，说明为什么这样判断）"
}}

**注意**：
1. 直接返回JSON，不要任何其他内容
2. summary要体现对用户真实意图的理解，不是简单重复用户的话
3. reasoning要说明你的判断依据，特别是为什么需要或不需要某个操作
4. 充分利用历史对话和富媒体卡片信息
5. 要有主动思考的意识，发现用户可能需要但没有明说的帮助

现在请开始分析："""

            messages = [Message(role=USER, content=analysis_prompt)]
            
            # 调用LLM进行快速分析
            response_text = ""
            if not self.agent or not self.agent.llm:
                raise ValueError("Agent或LLM未初始化")
            
            try:
                for output in self.agent.llm.chat(messages=messages, stream=True):
                    if output and len(output) > 0:
                        response_text = output[-1].content
            except Exception as e:
                logger.error(f"❌ LLM调用失败: {e}")
                raise ValueError(f"LLM调用失败: {e}")
            
            # 解析JSON响应
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                analysis_result = json.loads(json_match.group(0))
                logger.info(f"✅ 意图分析完成: {analysis_result.get('summary', '未知')}")
                if analysis_result.get('reasoning'):
                    logger.info(f"   分析推理: {analysis_result.get('reasoning')}")
                logger.info(f"   操作判断: 工具={analysis_result.get('need_tools')}, 更新待办={analysis_result.get('need_update_todo')}, 建议={analysis_result.get('need_suggestions')}")
                return analysis_result
            else:
                logger.warning("⚠️ AI返回格式不正确，使用关键词匹配")
                raise ValueError("JSON格式错误")
                
        except Exception as e:
            logger.warning(f"⚠️ AI意图分析失败，使用简单关键词匹配: {e}")
            # 回退到简单关键词匹配
            need_tools = any(keyword in content for keyword in ["天气", "导航", "打车", "酒店", "机票", "查询"])
            need_update_todo = any(keyword in content for keyword in ["补充", "完善", "修改", "添加", "更新", "详细"])
            need_suggestions = any(keyword in content for keyword in ["建议", "推荐", "准备", "计划", "提醒"])
            
            # 智能检查：如果已有相关卡片且用户不是明确要求更新，则不需要重新查询
            if rich_cards and need_tools:
                existing_card_types = {card.get('card_type') for card in rich_cards}
                
                # 检查是否明确要求更新/刷新
                is_explicit_update = any(keyword in content for keyword in ["更新", "刷新", "重新查询", "再查", "最新"])
                
                # 如果已有天气卡片且不是明确更新，可能不需要重新查询
                if "天气" in content and 'weather' in existing_card_types and not is_explicit_update:
                    logger.info("💡 检测到已有天气卡片，且用户未明确要求更新，可能不需要重新查询")
                    # 让Agent决定是否需要重新查询
                
                # 如果已有导航卡片且不是明确更新
                if any(kw in content for kw in ["导航", "路线", "怎么去"]) and 'navigation' in existing_card_types and not is_explicit_update:
                    logger.info("💡 检测到已有导航卡片，且用户未明确要求更新")
            
            return {
                "summary": "识别用户需求并制定执行计划",
                "need_tools": need_tools,
                "need_update_todo": need_update_todo,
                "need_suggestions": need_suggestions,
                "change_summary": "添加详细信息" if need_update_todo else None
            }
    
    
    def _format_sse_event(self, event_type: str, data: Any) -> str:
        """格式化SSE事件"""
        json_data = json.dumps(data, ensure_ascii=False)
        return f"event: {event_type}\ndata: {json_data}\n\n"


# 全局实例
_sse_service = None


def get_todo_chat_sse_service() -> TodoChatSSEService:
    """获取待办聊天SSE服务实例"""
    global _sse_service
    if _sse_service is None:
        _sse_service = TodoChatSSEService()
    return _sse_service



