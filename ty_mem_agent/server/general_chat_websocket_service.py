#!/usr/bin/env python3
"""
通用聊天WebSocket服务
处理实时对话、TTS、流式响应等
"""

import json
import uuid
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from loguru import logger
from fastapi import WebSocket, WebSocketDisconnect

from .general_chat_manager import get_general_chat_manager, SessionWrapper
from .tts_service import get_tts_service, TTSConfig
from .smart_sentence_splitter import get_sentence_splitter
from .user_manager import user_manager
from .scenarios import get_scenario_for_message
from .skills import get_skill_registry_lazy
from .todo_chat_sse_service import ExecutionStep
from ty_mem_agent.agents.ty_memory_agent import TYMemoryAgent
from qwen_agent.llm.schema import Message, USER


class GeneralChatWebSocketService:
    """通用聊天WebSocket服务"""
    
    def __init__(self):
        self.chat_manager = get_general_chat_manager()
        self.tts_service = get_tts_service()
        # 从配置文件读取分句模式
        self.sentence_splitter = get_sentence_splitter()
        
        # 活跃连接管理 {connection_id: websocket}
        self.active_connections: Dict[str, WebSocket] = {}
        
        # 用户连接映射 {user_id: connection_id}
        self.user_connections: Dict[int, str] = {}
        
        # 当前正在进行的生成任务 {connection_id: asyncio.Task}，用于 interrupt 取消
        self._generation_tasks: Dict[str, asyncio.Task] = {}
        
        logger.info("✅ 通用聊天WebSocket服务初始化完成")
    
    async def handle_connection(
        self,
        websocket: WebSocket,
        user_id: int
    ):
        """
        处理WebSocket连接
        
        Args:
            websocket: WebSocket连接
            user_id: 用户ID
        """
        connection_id = f"conn_{uuid.uuid4().hex[:12]}"
        
        try:
            # 接受连接
            await websocket.accept()
            
            # 注册连接
            self.active_connections[connection_id] = websocket
            self.user_connections[user_id] = connection_id
            
            logger.info(f"✅ WebSocket连接建立: user_id={user_id}, connection_id={connection_id}")
            
            # 发送连接成功消息
            await self._send_json(websocket, {
                "type": "connection_established",
                "user_id": user_id,
                "timestamp": datetime.now().isoformat()
            })
            
            # 消息处理循环
            while True:
                try:
                    # 接收客户端消息
                    message = await websocket.receive_json()
                    
                    # 处理消息；返回 "close" 表示客户端请求关闭，应退出循环
                    ret = await self._handle_client_message(
                        websocket=websocket,
                        user_id=user_id,
                        connection_id=connection_id,
                        message=message
                    )
                    if ret == "close":
                        break
                    
                except WebSocketDisconnect:
                    # 客户端主动断开连接，正常退出
                    logger.info(f"🔌 客户端断开连接: user_id={user_id}, connection_id={connection_id}")
                    break
                    
                except Exception as e:
                    # 检查是否是连接已断开的错误
                    error_str = str(e).lower()
                    if "disconnect" in error_str or "close" in error_str or "response already completed" in error_str:
                        logger.info(f"🔌 检测到连接已断开: user_id={user_id}, connection_id={connection_id}")
                        break
                    
                    logger.error(f"❌ 处理消息时出错: {e}")
                    try:
                        await self._send_json(websocket, {
                            "type": "error",
                            "code": 1001,
                            "message": f"处理消息失败: {str(e)}"
                        })
                    except Exception as send_error:
                        # 如果发送错误消息也失败，说明连接已断开
                        logger.info(f"🔌 发送错误消息失败，连接已断开: {send_error}")
                        break
                    
        except WebSocketDisconnect:
            logger.info(f"🔌 WebSocket连接断开: user_id={user_id}, connection_id={connection_id}")
        except Exception as e:
            logger.error(f"❌ WebSocket连接异常: {e}")
        finally:
            # 取消该连接上可能存在的生成任务
            gen_task = self._generation_tasks.pop(connection_id, None)
            if gen_task and not gen_task.done():
                gen_task.cancel()
            # 清理连接
            if connection_id in self.active_connections:
                del self.active_connections[connection_id]
            if user_id in self.user_connections:
                del self.user_connections[user_id]
            
            logger.info(f"🔌 WebSocket连接断开: user_id={user_id}, connection_id={connection_id}")
    
    async def _handle_client_message(
        self,
        websocket: WebSocket,
        user_id: int,
        connection_id: str,
        message: Dict
    ) -> Optional[str]:
        """
        处理客户端消息
        
        Args:
            websocket: WebSocket连接
            user_id: 用户ID
            connection_id: 连接ID
            message: 客户端消息
        
        Returns:
            "close" 表示客户端请求关闭，外层应退出接收循环；否则返回 None
        """
        msg_type = message.get("type")
        
        if msg_type == "ping":
            # 心跳响应
            await self._send_json(websocket, {
                "type": "pong",
                "timestamp": datetime.now().isoformat()
            })
            return None
            
        if msg_type == "close":
            # 客户端主动请求关闭连接（文档 3.1 节）
            logger.info(f"🔌 客户端请求关闭连接: user_id={user_id}, connection_id={connection_id}")
            try:
                await websocket.close()
            except Exception:
                pass
            return "close"
        
        if msg_type == "interrupt":
            # 中断当前 AI 回复（文档 3.1 节）
            task = self._generation_tasks.get(connection_id)
            if task and not task.done():
                task.cancel()
                logger.info(f"⏹️ 已响应 interrupt，取消生成: user_id={user_id}, connection_id={connection_id}")
            return None
            
        if msg_type == "send_message":
            # 取消该连接上已有的生成任务（若有）
            old_task = self._generation_tasks.pop(connection_id, None)
            if old_task and not old_task.done():
                old_task.cancel()
            # 发送聊天消息：放在后台任务中执行，以便能接收 interrupt/close
            task = asyncio.create_task(
                self._handle_send_message(
                    websocket=websocket,
                    user_id=user_id,
                    message=message,
                    connection_id=connection_id
                )
            )
            self._generation_tasks[connection_id] = task
            return None
            
        logger.warning(f"⚠️ 未知消息类型: {msg_type}")
        await self._send_json(websocket, {
            "type": "error",
            "code": 1002,
            "message": f"未知消息类型: {msg_type}"
        })
        return None
    
    async def _handle_send_message(
        self,
        websocket: WebSocket,
        user_id: int,
        message: Dict,
        connection_id: Optional[str] = None
    ):
        """
        处理发送消息请求
        
        Args:
            websocket: WebSocket连接
            user_id: 用户ID
            message: 客户端消息
            connection_id: 连接ID，用于 interrupt 时清理任务引用
        """
        try:
            await self._handle_send_message_impl(
                websocket=websocket,
                user_id=user_id,
                message=message,
                connection_id=connection_id
            )
        except asyncio.CancelledError:
            # 被 interrupt 或 close 取消：发送 done（interrupted）后重新抛出
            logger.info(f"⏹️ 生成被取消: user_id={user_id}")
            try:
                await self._send_json(websocket, {
                    "type": "done",
                    "message_id": None,
                    "full_content": "",
                    "total_audio_duration_ms": 0,
                    "interrupted": True,
                    "timestamp": datetime.now().isoformat()
                })
            except Exception:
                pass
            raise
        finally:
            if connection_id:
                self._generation_tasks.pop(connection_id, None)
    
    async def _handle_send_message_impl(
        self,
        websocket: WebSocket,
        user_id: int,
        message: Dict,
        connection_id: Optional[str] = None
    ):
        """发送消息的实现逻辑（供 _handle_send_message 调用，便于在取消时发送 done）"""
        # 解析参数
        session_id = message.get("session_id")
        user_message = message.get("message", "")
        enable_tts = message.get("enable_tts", False)
        tts_config = message.get("tts_config", {})
        client_type = message.get("client_type", "app")  # app 或 glasses
        deep_thinking = message.get("deep_thinking", False)
        # 仅 APP 端支持深度思考，眼镜端强制关闭
        if client_type != "app":
            deep_thinking = False
        
        logger.info(f"📥 收到用户消息: user_id={user_id}, session_id={session_id}, "
                   f"message_len={len(user_message)}, enable_tts={enable_tts}, "
                   f"client_type={client_type}, deep_thinking={deep_thinking}")
        
        if not user_message or not user_message.strip():
            await self._send_json(websocket, {
                "type": "error",
                "code": 1003,
                "message": "消息内容不能为空"
            })
            return
        
        try:
            # ========== 1. 初始化或获取会话 ==========
            if session_id:
                session = self.chat_manager.get_session(session_id)
                if not session:
                    await self._send_json(websocket, {
                        "type": "error",
                        "code": 1004,
                        "message": f"会话不存在: {session_id}"
                    })
                    return
                if session.user_id != user_id:
                    await self._send_json(websocket, {
                        "type": "error",
                        "code": 1005,
                        "message": "无权访问此会话"
                    })
                    return
            else:
                # 创建新会话
                session = self.chat_manager.create_session(
                    user_id=user_id,
                    title="新对话"
                )
                session_id = session.session_id
                
                # 发送会话创建事件
                await self._send_json(websocket, {
                    "type": "session_init",
                    "session_id": session_id,
                    "title": session.title,
                    "created_at": session.created_at
                })
            
            # ========== 2. 保存用户消息 ==========
            user_msg = self.chat_manager.add_message(
                session_id=session_id,
                role="user",
                content=user_message
            )
            
            if not user_msg:
                await self._send_json(websocket, {
                    "type": "error",
                    "code": 1006,
                    "message": "保存用户消息失败"
                })
                return
            
            # 发送消息接收确认
            await self._send_json(websocket, {
                "type": "message_received",
                "message_id": user_msg.message_id,
                "timestamp": user_msg.timestamp
            })
            
            # ========== 2.5 打车确认：若有待确认叫车且本条为确认信息，则直接调用 taxi_create_order，不经过 Agent ==========
            pending_ride = self.chat_manager.get_pending_ride(session_id)
            if pending_ride and self._is_ride_confirm_message(user_message):
                handled = await self._handle_ride_confirm_and_create_order(
                    websocket=websocket,
                    session_id=session_id,
                    user_id=user_id,
                    user_message=user_message,
                    pending_ride=pending_ride,
                    enable_tts=enable_tts,
                    tts_config=tts_config,
                )
                if handled:
                    return
            
            # ========== 2.6 取消叫车：若用户明确要取消订单且本会话有最近订单号，则直接调用 taxi_cancel_order，不经过 Agent ==========
            if self._is_ride_cancel_message(user_message):
                order_id = self.chat_manager.get_last_ride_order_id(session_id)
                if order_id:
                    tts_cfg_for_cancel = None
                    if enable_tts:
                        from ty_mem_agent.config.settings import settings
                        tts_cfg_for_cancel = TTSConfig(
                            model=tts_config.get("model", settings.TTS_MODEL),
                            voice=tts_config.get("voice", settings.TTS_VOICE),
                            language_type=tts_config.get("language_type", settings.TTS_LANGUAGE_TYPE),
                        )
                    handled = await self._handle_ride_cancel_and_call_mcp(
                        websocket=websocket,
                        session_id=session_id,
                        user_id=user_id,
                        order_id=order_id,
                        enable_tts=enable_tts,
                        tts_config=tts_cfg_for_cancel,
                    )
                    if handled:
                        return
            
            # ========== 3. 调用Agent处理 ==========
            # 发送开始生成事件
            await self._send_json(websocket, {
                "type": "generation_started",
                "timestamp": datetime.now().isoformat()
            })
            enable_deep_thinking = bool(deep_thinking and client_type == "app")
            thinking_steps: List[ExecutionStep] = []
            business_actions_done: List[str] = []
            plan_result: Optional[Dict[str, Any]] = None
            if enable_deep_thinking:
                # 深度思考模式：先调用大模型做任务规划；多轮对话时传入最近几轮，避免把简短回复（如「万科锦绣滨江」）误判成新意图
                from .deep_thinking_planner import plan_with_llm
                recent_dialogue: List[Dict[str, str]] = []
                if session and getattr(session, "messages", None):
                    # 最近 6 条（约 3 轮），不含本条用户消息
                    recent = session.messages[-6:] if len(session.messages) > 6 else session.messages
                    for msg in recent:
                        recent_dialogue.append({"role": getattr(msg, "role", "user"), "content": getattr(msg, "content", "") or ""})
                try:
                    plan_result = await asyncio.wait_for(
                        asyncio.to_thread(plan_with_llm, user_message or "", 15.0, recent_dialogue),
                        timeout=18.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning("深度思考规划超时，使用模板")
                    plan_result = None
                except Exception as e:
                    logger.warning(f"深度思考规划失败: {e}，使用模板")
                    plan_result = None
                if plan_result and plan_result.get("plan_text") and plan_result.get("steps"):
                    plan_text = plan_result["plan_text"]
                    thinking_steps = []
                    for i, s in enumerate(plan_result["steps"], start=1):
                        step_type = (s.get("type") or "tool").strip().lower()
                        if step_type not in ("analysis", "tool", "generate", "update"):
                            step_type = "tool"
                        desc = (s.get("desc") or "").strip() or "执行该步骤"
                        thinking_steps.append(ExecutionStep(i, step_type, desc))
                    if thinking_steps:
                        thinking_steps[0].update_status("running", desc=thinking_steps[0].desc, progress=0.1)
                else:
                    # 规划失败或返回无效时退回通用模板（不提及具体业务场景以免张冠李戴）
                    preview = (user_message or "").strip()
                    if len(preview) > 40:
                        preview = preview[:40] + "…"
                    analysis_desc = f"理解您的问题并制定处理方案" if not preview else f"分析「{preview}」的具体需求"
                    thinking_steps = [
                        ExecutionStep(1, "analysis", analysis_desc),
                        ExecutionStep(2, "tool", "按需查询和获取相关信息"),
                        ExecutionStep(3, "generate", "整理信息并给出回复"),
                    ]
                    thinking_steps[0].update_status("running", desc=analysis_desc, progress=0.1)
                    plan_text = f"正在分析您的问题并规划处理步骤。" if not preview else f"正在分析「{preview}」，规划处理步骤。"
                await self._send_json(websocket, {
                    "type": "thinking",
                    "step": "plan",
                    "content": plan_text,
                    "timestamp": datetime.now().isoformat(),
                })
                await self._send_json(websocket, {
                    "type": "plan_update",
                    "steps": [s.to_dict() for s in thinking_steps],
                    "timestamp": datetime.now().isoformat(),
                })
            
            # 若是新会话首轮：并发生成标题，标题就绪即推 title_updated，便于 APP 尽早展示会话标题
            if session and len(session.messages) == 1:
                asyncio.create_task(self._send_title_when_ready(
                    websocket=websocket,
                    session_id=session_id,
                    user_message=user_message
                ))
            
            # 准备历史消息
            history_messages = self._prepare_history_messages(session)
            
            # 创建Agent（每次创建新实例以避免状态污染）
            # 如果启用TTS，使用专门优化的系统提示词（要求回答200字符以内）
            if enable_tts:
                tts_system_message = TYMemoryAgent.build_tts_optimized_system_message()
                agent = TYMemoryAgent(system_message=tts_system_message)
                logger.debug("🎤 使用TTS优化的系统提示词（200字符限制）")
            else:
                agent = TYMemoryAgent()
            # 与 APP API 一致：连接上的 user_id 为 calendar_user_id，需解析为内部 user_id，
            # 日历等 MCP 工具通过 agent 上下文拿到的是 user_manager 可识别的内部 id
            agent_user_id = str(user_id)
            user = user_manager.get_or_create_user_by_calendar_id(user_id)
            if user:
                agent_user_id = user.user_id
                logger.debug(f"🔄 WebSocket 用户解析: calendar_user_id={user_id} -> agent user_id={agent_user_id}")
            else:
                logger.warning(f"⚠️ 无法解析 calendar_user_id={user_id} 为内部用户，日历等工具可能不可用")
            await agent.set_user_context(user_id=agent_user_id, session_id=session_id)
            
            # 流式调用Agent
            full_response = ""
            current_sentence = ""
            thinking_step_index = 0
            
            # 准备TTS配置
            tts_cfg = None
            if enable_tts:
                # 从配置文件获取默认值，客户端可覆盖
                from ty_mem_agent.config.settings import settings
                tts_cfg = TTSConfig(
                    model=tts_config.get("model", settings.TTS_MODEL),
                    voice=tts_config.get("voice", settings.TTS_VOICE),
                    language_type=tts_config.get("language_type", settings.TTS_LANGUAGE_TYPE)
                )
            
            # 本轮对话中 get_user_profile 返回的 phone，用于同轮后续打车卡片的电话展示
            _cached_phone_from_get_user_profile = None
            # 本轮是否已推送“车型选择”打车卡片（用于 done 时修正 full_content，避免仍以“请提供电话”结尾）
            _pushed_ride_confirm_cards_this_turn = False
            # 本轮打车卡片的起点、终点（用于 TTS 兜底句：“起点是XX，终点是YY，请确认…”）
            _last_ride_origin: Optional[str] = None
            _last_ride_destination: Optional[str] = None
            # 叫车场景：在「已查到/请提供电话」之后、推送车型卡片之前，不 TTS 模型中间输出（如「北门位置…」）
            _ride_hailing_suppress_tts_until_cards = False
            # 本轮已发送过「请确认起终点并选择车型」整句（避免模型尾随输出「车型。」再触发一次重复的 sentence_complete + TTS，且不再下发该尾随 message_delta）
            _ride_confirm_tts_sent_this_turn = False
            _last_ride_confirm_tts_sent: Optional[str] = None
            # 本回合是否进入某场景（打车等），用于委托 TTS/抑制 决策
            _scenario = get_scenario_for_message(user_message)
            
            async for chunk in self._stream_agent_response(
                agent, history_messages, deep_thinking,
                plan_result=plan_result if enable_deep_thinking and plan_result else None,
            ):
                chunk_type = chunk.get("type")
                
                if chunk_type == "delta":
                    # 文本增量
                    delta_text = chunk.get("content", "")
                    full_response += delta_text
                    current_sentence += delta_text
                    # 叫车场景：在「已查到/请提供电话」之后、推送车型卡片之前，既不 TTS 也不把模型的中间句作为 message_delta 下发；推送车型卡片并播报完整句之后，模型的尾随输出（如「车型。」）也不再下发，避免重复语音与不通顺片段
                    _suppress_model_stream = (
                        (_ride_hailing_suppress_tts_until_cards and not _pushed_ride_confirm_cards_this_turn)
                        or _ride_confirm_tts_sent_this_turn
                    )
                    if not _suppress_model_stream:
                        await self._send_json(websocket, {
                            "type": "message_delta",
                            "content": delta_text,
                            "timestamp": datetime.now().isoformat()
                        })
                    # 检查是否完成了一个句子（用于TTS）
                    if enable_tts and self._is_sentence_complete(current_sentence):
                        raw_sentence = current_sentence.strip()
                        # 场景层：若本回合进入某场景，由场景决定是否 TTS；否则用叫车标志
                        _scenario_ctx = {
                            "ride_hailing_suppress_tts_until_cards": _ride_hailing_suppress_tts_until_cards,
                            "ride_hailing_pushed_confirm_cards": _pushed_ride_confirm_cards_this_turn,
                        }
                        skip_tts = (
                            (_scenario and not _scenario.should_tts_model_output(_scenario_ctx))
                            or (not _scenario and _ride_hailing_suppress_tts_until_cards and not _pushed_ride_confirm_cards_this_turn)
                        )
                        if skip_tts:
                            current_sentence = ""
                            continue
                        # 无意义片段（如 ".."、"。"）不播报
                        if not self._is_meaningful_tts_sentence(raw_sentence):
                            current_sentence = ""
                            continue
                        # 叫车确认场景：残句（如「车型。」）替换为完整句；若本轮已发送过该完整句（注入的 ride_confirm_tts），不再重复 sentence_complete + TTS
                        tts_text = self._get_ride_confirm_tts_text(
                            raw_sentence, _last_ride_origin, _last_ride_destination
                        ) or raw_sentence
                        if _ride_confirm_tts_sent_this_turn and tts_text == _last_ride_confirm_tts_sent:
                            current_sentence = ""
                            continue
                        # 发送句子完成事件（对外展示用原始句，TTS 用 tts_text）
                        await self._send_json(websocket, {
                            "type": "sentence_complete",
                            "sentence": tts_text,
                            "timestamp": datetime.now().isoformat()
                        })
                        await self._generate_and_send_audio(
                            websocket=websocket,
                            text=tts_text,
                            tts_config=tts_cfg
                        )
                        current_sentence = ""
                
                # elif chunk_type == "tool_call":
                #     # 工具调用
                #     await self._send_json(websocket, {
                #         "type": "tool_call",
                #         "tool_name": chunk.get("tool_name"),
                #         "tool_args": chunk.get("tool_args"),
                #         "timestamp": datetime.now().isoformat()
                #     })
                
                elif chunk_type == "tool_result":
                    # 工具结果
                    tool_name = chunk.get("tool_name")
                    tool_result = chunk.get("result")
                    tool_args = chunk.get("tool_args")  # cancel 时用于从参数取 eventId
                    
                    # 深度思考模式：将每次工具完成视为执行计划中的进度更新
                    if enable_deep_thinking and thinking_steps:
                        thinking_step_index += 1
                        short_desc = get_skill_registry_lazy().get_business_short(tool_name)
                        business_actions_done.append("已" + short_desc)
                        # 按 type 找到对应的步骤并更新，不硬编码索引
                        for s in thinking_steps:
                            if s.type == "analysis" and s.status != "completed":
                                s.update_status("completed", progress=1.0)
                                break
                        # 更新 tool 步骤进度：优先保留规划器给出的具体 desc，只在无内容时用 skills 兜底
                        for s in thinking_steps:
                            if s.type == "tool":
                                cur = s.progress or 0.0
                                new_prog = min(cur + 0.3, 0.95)
                                original_desc = s.desc or ""
                                if original_desc and not original_desc.startswith("正在"):
                                    running_desc = f"正在{original_desc}"
                                elif original_desc:
                                    running_desc = original_desc
                                else:
                                    running_desc = f"正在{short_desc}…"
                                s.update_status("running", desc=running_desc, progress=new_prog)
                                break

                        thinking_content = get_skill_registry_lazy().get_thinking_after_result(tool_name, tool_result)
                        await self._send_json(websocket, {
                            "type": "thinking",
                            "step": thinking_step_index,
                            "content": thinking_content,
                            "timestamp": datetime.now().isoformat(),
                        })
                        await self._send_json(websocket, {
                            "type": "plan_update",
                            "steps": [s.to_dict() for s in thinking_steps],
                            "timestamp": datetime.now().isoformat(),
                        })
                    
                    # 发送工具结果事件
                    await self._send_json(websocket, {
                        "type": "tool_result",
                        "tool_name": tool_name,
                        "result": tool_result,
                        "timestamp": datetime.now().isoformat()
                    })
                    
                    # 仅对指定类型工具生成富媒体卡片：待办（日历）、打车（订单确认/订单生成中/已接单），其余工具不生成卡片
                    if tool_result is not None or tool_args is not None:
                        from ty_mem_agent.server.rich_card_manager import (
                            build_todo_card_from_calendar_result,
                            build_ride_hailing_cards_from_didi_result,
                            build_weather_card_from_amap_result,
                            get_rich_card_manager,
                            parse_estimate_flow_id_from_taxi_estimate_result,
                            parse_estimate_trace_id_from_taxi_estimate_result,
                        )
                        card_manager = get_rich_card_manager()
                        result_for_extract = (
                            str(tool_result) if not isinstance(tool_result, (dict, list)) else tool_result
                        )

                        # 同轮内缓存 get_user_profile 返回的 phone，供后续打车卡片使用；并注入一句 TTS（已查到/请提供电话）
                        if tool_name == "get_user_profile" and tool_result:
                            try:
                                import json as _json
                                res = tool_result if isinstance(tool_result, dict) else _json.loads(str(tool_result))
                                if isinstance(res, dict) and res.get("success"):
                                    profile = res.get("profile") if isinstance(res.get("profile"), dict) else None
                                    if profile:
                                        ph = profile.get("phone")
                                        if ph and str(ph).strip():
                                            _cached_phone_from_get_user_profile = str(ph).strip()
                            except Exception:
                                pass
                            _scenario_ctx = {
                                "ride_hailing_suppress_tts_until_cards": _ride_hailing_suppress_tts_until_cards,
                                "ride_hailing_pushed_confirm_cards": _pushed_ride_confirm_cards_this_turn,
                                "user_message": user_message,
                            }
                            if _scenario:
                                action = _scenario.on_tool_result(
                                    tool_name, tool_result, tool_args, _scenario_ctx
                                )
                                if action and action.tts_to_say:
                                    if enable_tts:
                                        await self._emit_message_delta_for_sentence(websocket, action.tts_to_say)
                                        await self._send_json(websocket, {
                                            "type": "sentence_complete",
                                            "sentence": action.tts_to_say,
                                            "timestamp": datetime.now().isoformat(),
                                        })
                                        await self._generate_and_send_audio(
                                            websocket=websocket,
                                            text=action.tts_to_say,
                                            tts_config=tts_cfg,
                                        )
                                    full_response += "\n\n" + action.tts_to_say
                                    if action.suppress_tts_until_cards:
                                        _ride_hailing_suppress_tts_until_cards = True
                            else:
                                if enable_tts:
                                    from ty_mem_agent.server.scenarios.ride_hailing import user_only_said_destination
                                    if _cached_phone_from_get_user_profile and user_only_said_destination(user_message):
                                        profile_tts = "已查到您的电话号码。请问您的上车地点是哪里？"
                                    else:
                                        profile_tts = (
                                            "已查到您的电话号码，正在为您查询车型与价格。"
                                            if _cached_phone_from_get_user_profile
                                            else "请提供您的电话号码，以便为您叫车。"
                                        )
                                    await self._emit_message_delta_for_sentence(websocket, profile_tts)
                                    await self._send_json(websocket, {
                                        "type": "sentence_complete",
                                        "sentence": profile_tts,
                                        "timestamp": datetime.now().isoformat(),
                                    })
                                    await self._generate_and_send_audio(
                                        websocket=websocket,
                                        text=profile_tts,
                                        tts_config=tts_cfg,
                                    )
                                    full_response += "\n\n" + profile_tts
                                    _ride_hailing_suppress_tts_until_cards = True

                        # 滴滴打车 MCP：三阶段流程（确认订单、执行中、成功）
                        # 获取用户电话号码（画像优先，同轮 get_user_profile 缓存，否则从本会话最近用户消息中解析）
                        user_phone = None
                        if tool_name and "Didi-Ride-" in tool_name:
                            try:
                                from ty_mem_agent.memory.user_memory import get_integrated_memory
                                integrated_memory = get_integrated_memory()
                                profile = integrated_memory.user_manager.get_user_profile(agent_user_id)
                                if profile and hasattr(profile, 'phone') and profile.phone:
                                    user_phone = profile.phone
                            except Exception as e:
                                logger.debug(f"获取用户电话号码失败（不影响叫车流程）: {e}")
                            if not user_phone and session_id:
                                import re
                                try:
                                    recent = self.chat_manager.get_session_messages(session_id, limit=10)
                                    for msg in reversed(recent or []):
                                        if getattr(msg, "role", None) != "user":
                                            continue
                                        content = (getattr(msg, "content", None) or "") or ""
                                        m = re.search(r"1[3-9]\d{9}", content)
                                        if m:
                                            user_phone = m.group(0)
                                            break
                                except Exception as e:
                                    logger.debug(f"从会话消息解析电话失败: {e}")
                            user_phone = user_phone or _cached_phone_from_get_user_profile
                        
                        ride_cards = build_ride_hailing_cards_from_didi_result(
                            tool_name=tool_name,
                            tool_result=result_for_extract if tool_result is not None else "{}",
                            user_id=user_id,
                            user_phone=user_phone,
                            tool_args=tool_args,
                        )
                        # 记录本轮打车起点终点，供 TTS 兜底句使用；并保存待确认叫车上下文（含 estimate_flow_id）供用户确认后直接下单
                        if ride_cards and tool_args:
                            try:
                                args = tool_args if isinstance(tool_args, dict) else json.loads(str(tool_args))
                                if isinstance(args, dict):
                                    _last_ride_origin = args.get("from_name")
                                    _last_ride_destination = args.get("to_name")
                                    if tool_name == "Didi-Ride-taxi_estimate":
                                        flow_id = parse_estimate_flow_id_from_taxi_estimate_result(
                                            result_for_extract if tool_result is not None else ""
                                        )
                                        if flow_id:
                                            trace_id = parse_estimate_trace_id_from_taxi_estimate_result(
                                                result_for_extract if tool_result is not None else ""
                                            )
                                            pending = {
                                                "estimate_flow_id": flow_id,
                                                "estimate_trace_id": trace_id,
                                                "from_lng": args.get("from_lng"),
                                                "from_lat": args.get("from_lat"),
                                                "from_name": args.get("from_name"),
                                                "to_lng": args.get("to_lng"),
                                                "to_lat": args.get("to_lat"),
                                                "to_name": args.get("to_name"),
                                                "user_phone": user_phone,
                                            }
                                            self.chat_manager.set_pending_ride(session_id, pending)
                                            logger.info(f"✅ 已保存待确认叫车上下文: estimate_flow_id={flow_id[:16]}..., estimate_trace_id={trace_id[:16] if trace_id else 'None'}...")
                            except Exception as e:
                                logger.debug(f"保存待确认叫车上下文失败: {e}")
                        if ride_cards:
                            for card in ride_cards:
                                try:
                                    card_manager.create_card(
                                        event_id=0,  # 打车订单不关联待办
                                        user_id=user_id,
                                        card_type=card.get("card_type", "ride_hailing"),
                                        title=card.get("title", "打车信息"),
                                        subtitle=card.get("subtitle"),
                                        icon=card.get("icon"),
                                        data=card.get("data", {}),
                                        source=card.get("source", "通用聊天-滴滴打车"),
                                        expires_at=card.get("expires_at"),
                                        card_id=card.get("card_id"),
                                    )
                                    self.chat_manager.add_card_to_session(session_id=session_id, card=card)
                                    await self._send_json(websocket, {
                                        "type": "rich_card",
                                        "card_id": card.get("card_id"),
                                        "card_type": card.get("card_type"),
                                        "title": card.get("title"),
                                        "subtitle": card.get("subtitle"),
                                        "icon": card.get("icon"),
                                        "data": card.get("data", {}),
                                        "source": card.get("source"),
                                        "created_at": card.get("created_at"),
                                        "updated_at": card.get("updated_at"),
                                        "expires_at": card.get("expires_at"),
                                        "timestamp": datetime.now().isoformat(),
                                    })
                                    logger.info(f"🎴 打车卡片已创建并推送: {card.get('card_type')} - {card.get('title')}")
                                    if (card.get("data") or {}).get("stage") == "confirm":
                                        _pushed_ride_confirm_cards_this_turn = True
                                except Exception as e:
                                    logger.warning(f"⚠️ 打车卡片创建失败: {e}")
                            # 已推送车型卡片：解除 TTS 抑制，并播报一句「请确认起点终点并选择车型」
                            if _pushed_ride_confirm_cards_this_turn and enable_tts:
                                _ride_hailing_suppress_tts_until_cards = False
                                ride_confirm_tts = None
                                if _scenario:
                                    _scenario_ctx = {
                                        "ride_hailing_suppress_tts_until_cards": _ride_hailing_suppress_tts_until_cards,
                                        "ride_hailing_pushed_confirm_cards": _pushed_ride_confirm_cards_this_turn,
                                    }
                                    action = _scenario.on_tool_result(
                                        tool_name, result_for_extract, tool_args, _scenario_ctx
                                    )
                                    if action and action.tts_after_ride_confirm_cards:
                                        ride_confirm_tts = action.tts_after_ride_confirm_cards
                                if ride_confirm_tts is None:
                                    ride_confirm_tts = self._get_ride_confirm_tts_text(
                                        "车型。", _last_ride_origin, _last_ride_destination
                                    ) or "已为您查询到几种车型与预估价格，请确认起终点无误后选择一种车型。"
                                await self._emit_message_delta_for_sentence(websocket, ride_confirm_tts)
                                await self._send_json(websocket, {
                                    "type": "sentence_complete",
                                    "sentence": ride_confirm_tts,
                                    "timestamp": datetime.now().isoformat(),
                                })
                                await self._generate_and_send_audio(
                                    websocket=websocket,
                                    text=ride_confirm_tts,
                                    tts_config=tts_cfg,
                                )
                                _ride_confirm_tts_sent_this_turn = True
                                _last_ride_confirm_tts_sent = ride_confirm_tts
                            # 若为本轮推送的订单成功卡片，则记录订单号并后台轮询订单状态，司机接单后推送司机卡片并 TTS
                            for card in (ride_cards or []):
                                data = card.get("data") or {}
                                if data.get("stage") == "success" and data.get("order_id"):
                                    self.chat_manager.set_last_ride_order_id(session_id, data["order_id"])
                                    asyncio.create_task(self._poll_ride_order_until_driver(
                                        websocket=websocket,
                                        session_id=session_id,
                                        user_id=user_id,
                                        order_id=data["order_id"],
                                        enable_tts=enable_tts,
                                        tts_config=tts_cfg,
                                    ))
                                    break

                        # 日历 MCP：待办创建/更新/删除 → 本地待办卡片（无则新建，有则更新/删除）
                        todo_out = build_todo_card_from_calendar_result(
                            tool_name=tool_name,
                            tool_result=result_for_extract if tool_result is not None else "{}",
                            user_id=user_id,
                            tool_args=tool_args,
                        )
                        if todo_out is not None:
                            card_or_none, ev_id, action = todo_out
                            if action == "create" and card_or_none:
                                # 无则新建，有则更新
                                cid = card_or_none.get("card_id")
                                existing = card_manager.get_card(cid) if cid else None
                                try:
                                    if existing:
                                        card_manager.update_card(
                                            cid,
                                            title=card_or_none.get("title"),
                                            subtitle=card_or_none.get("subtitle"),
                                            data=card_or_none.get("data"),
                                            source=card_or_none.get("source"),
                                        )
                                        logger.info(f"🎴 待办卡片已更新并推送: event_id={ev_id}, title={card_or_none.get('title')}")
                                    else:
                                        card_manager.create_card(
                                            event_id=ev_id,
                                            user_id=user_id,
                                            card_type="todo",
                                            title=card_or_none.get("title", "待办"),
                                            subtitle=card_or_none.get("subtitle"),
                                            icon=card_or_none.get("icon"),
                                            data=card_or_none.get("data", {}),
                                            source=card_or_none.get("source", "通用聊天-日历"),
                                            expires_at=card_or_none.get("expires_at"),
                                            card_id=card_or_none.get("card_id"),
                                        )
                                        self.chat_manager.add_card_to_session(session_id=session_id, card=card_or_none)
                                        logger.info(f"🎴 待办卡片已创建并推送: event_id={ev_id}, title={card_or_none.get('title')}")
                                    await self._send_json(websocket, {
                                        "type": "rich_card",
                                        "card_id": card_or_none.get("card_id"),
                                        "card_type": "todo",
                                        "title": card_or_none.get("title"),
                                        "subtitle": card_or_none.get("subtitle"),
                                        "icon": card_or_none.get("icon"),
                                        "data": card_or_none.get("data", {}),
                                        "source": card_or_none.get("source"),
                                        "created_at": card_or_none.get("created_at"),
                                        "updated_at": card_or_none.get("updated_at"),
                                        "expires_at": card_or_none.get("expires_at"),
                                        "timestamp": datetime.now().isoformat(),
                                    })
                                except Exception as e:
                                    logger.warning(f"⚠️ 待办卡片创建/更新失败: {e}")
                            elif action == "update" and card_or_none:
                                cid = card_or_none.get("card_id")
                                existing = card_manager.get_card(cid) if cid else None
                                if existing:
                                    try:
                                        card_manager.update_card(
                                            cid,
                                            title=card_or_none.get("title"),
                                            subtitle=card_or_none.get("subtitle"),
                                            data=card_or_none.get("data"),
                                            source=card_or_none.get("source"),
                                        )
                                        await self._send_json(websocket, {
                                            "type": "rich_card",
                                            "card_id": cid,
                                            "card_type": "todo",
                                            "title": card_or_none.get("title"),
                                            "subtitle": card_or_none.get("subtitle"),
                                            "icon": card_or_none.get("icon"),
                                            "data": card_or_none.get("data", {}),
                                            "source": card_or_none.get("source"),
                                            "created_at": card_or_none.get("created_at"),
                                            "updated_at": card_or_none.get("updated_at"),
                                            "expires_at": card_or_none.get("expires_at"),
                                            "timestamp": datetime.now().isoformat(),
                                        })
                                        logger.info(f"🎴 待办卡片已更新并推送: event_id={ev_id}")
                                    except Exception as e:
                                        logger.warning(f"⚠️ 待办卡片更新失败: {e}")
                            elif action == "delete":
                                try:
                                    # 先取出该 event 下的卡片，从当前会话中移除关联，再删物理卡片，保证会话/历史里不再出现
                                    to_remove = card_manager.get_cards_by_event(ev_id, user_id=user_id)
                                    for c in to_remove:
                                        self.chat_manager.remove_card_from_session(session_id, c.card_id)
                                    n = card_manager.delete_cards_by_event(ev_id, user_id)
                                    await self._send_json(websocket, {
                                        "type": "todo_card_deleted",
                                        "event_id": ev_id,
                                        "deleted_count": n,
                                        "timestamp": datetime.now().isoformat(),
                                    })
                                    logger.info(f"🎴 待办卡片已删除: event_id={ev_id}, count={n}")
                                except Exception as e:
                                    logger.warning(f"⚠️ 待办卡片删除失败: {e}")

                        # 高德天气 MCP：从 maps_weather 结果生成天气卡片并推送（结合用户原始问题选择合适日期，如“明天重庆天气”选用明日预报）
                        weather_card = build_weather_card_from_amap_result(
                            tool_name=tool_name or "",
                            tool_result=result_for_extract if tool_result is not None else "{}",
                            user_id=user_id,
                            user_query=user_message,
                        )
                        if weather_card:
                            try:
                                card_manager.create_card(
                                    event_id=0,
                                    user_id=user_id,
                                    card_type=weather_card.get("card_type", "weather"),
                                    title=weather_card.get("title", "天气"),
                                    subtitle=weather_card.get("subtitle"),
                                    icon=weather_card.get("icon"),
                                    data=weather_card.get("data", {}),
                                    source=weather_card.get("source", "通用聊天-高德天气"),
                                    expires_at=weather_card.get("expires_at"),
                                    card_id=weather_card.get("card_id"),
                                )
                                self.chat_manager.add_card_to_session(session_id=session_id, card=weather_card)
                                await self._send_json(websocket, {
                                    "type": "rich_card",
                                    "card_id": weather_card.get("card_id"),
                                    "card_type": weather_card.get("card_type"),
                                    "title": weather_card.get("title"),
                                    "subtitle": weather_card.get("subtitle"),
                                    "icon": weather_card.get("icon"),
                                    "data": weather_card.get("data", {}),
                                    "source": weather_card.get("source"),
                                    "created_at": weather_card.get("created_at"),
                                    "updated_at": weather_card.get("updated_at"),
                                    "expires_at": weather_card.get("expires_at"),
                                    "timestamp": datetime.now().isoformat(),
                                })
                                logger.info(f"🎴 天气卡片已创建并推送: {weather_card.get('card_type')} - {weather_card.get('title')}")
                            except Exception as e:
                                logger.warning(f"⚠️ 天气卡片创建失败: {e}")

                        # 其余工具（POI、get_user_profile 等）默认不生成卡片；
                        # 若以后需要某类工具生成卡片，可在此按 tool_name 单独处理。
            
            # 处理剩余的未完成句子（如果启用了TTS）
            if enable_tts and current_sentence.strip():
                # 叫车场景：若仍在「等车型卡片」阶段，不 TTS 剩余模型输出
                if _ride_hailing_suppress_tts_until_cards and not _pushed_ride_confirm_cards_this_turn:
                    pass
                else:
                    raw_sentence = current_sentence.strip()
                    if self._is_meaningful_tts_sentence(raw_sentence):
                        tts_text = self._get_ride_confirm_tts_text(
                            raw_sentence, _last_ride_origin, _last_ride_destination
                        ) or raw_sentence
                        await self._send_json(websocket, {
                            "type": "sentence_complete",
                            "sentence": tts_text,
                            "timestamp": datetime.now().isoformat()
                        })
                        await self._generate_and_send_audio(
                            websocket=websocket,
                            text=tts_text,
                            tts_config=tts_cfg
                        )
            
            # ========== 4. 保存AI回复 ==========
            if full_response.strip():
                # 若本轮已推送车型选择卡片，用一句完整提示作为最终展示（避免“请提供电话”或残句“车型。”）
                final_content = full_response.strip()
                if _pushed_ride_confirm_cards_this_turn:
                    fallback = self._get_ride_confirm_tts_text(
                        final_content, _last_ride_origin, _last_ride_destination
                    )
                    if fallback:
                        final_content = fallback
                    elif "请提供您的电话号码" in final_content or final_content.endswith("以便为您叫车。"):
                        final_content = "已为您查询到几种车型与预估价格，请确认起终点无误后选择一种车型。"
                
                # 获取会话的富媒体卡片
                rich_cards = self.chat_manager.get_session_cards(session_id) or []
                
                ai_msg = self.chat_manager.add_message(
                    session_id=session_id,
                    role="assistant",
                    content=final_content,
                    rich_cards=rich_cards
                )
                
                # 发送完成事件
                await self._send_json(websocket, {
                    "type": "done",
                    "message_id": ai_msg.message_id if ai_msg else None,
                    "full_content": final_content,
                    "total_audio_duration_ms": 0,  # 若有 TTS 可在此累加各句 duration_ms
                    "timestamp": datetime.now().isoformat()
                })
            
            else:
                # 没有生成内容
                await self._send_json(websocket, {
                    "type": "done",
                    "message_id": None,
                    "full_content": "",
                    "total_audio_duration_ms": 0,
                    "timestamp": datetime.now().isoformat()
                })
            # 深度思考模式：在 done 之后把所有未完成步骤标为 completed，并生成收尾 thinking
            if enable_deep_thinking and thinking_steps:
                def _completed_desc(step: ExecutionStep) -> str:
                    d = step.desc or ""
                    if d.startswith("正在"):
                        d = d[2:].rstrip("…").rstrip("...").strip()
                        return f"已完成{d}" if d else "已完成"
                    return d if d else "已完成"
                for s in thinking_steps:
                    if s.status != "completed":
                        s.update_status("completed", desc=_completed_desc(s), progress=1.0)
                await self._send_json(websocket, {
                    "type": "plan_update",
                    "steps": [s.to_dict() for s in thinking_steps],
                    "timestamp": datetime.now().isoformat(),
                })
                # 用规划器生成的 plan_text 和实际执行的业务动作做收尾，不用固定模板
                original_plan = plan_result.get("plan_text", "") if plan_result else ""
                if business_actions_done and original_plan:
                    summary_text = f"深度思考完成。本次规划：{original_plan}。实际执行：{'、'.join(business_actions_done)}，已整合信息给出回复。"
                elif business_actions_done:
                    summary_text = f"深度思考完成。{'、'.join(business_actions_done)}，已整合信息给出回复。"
                elif original_plan:
                    summary_text = f"深度思考完成。{original_plan}，已直接给出回复。"
                else:
                    summary_text = "深度思考完成，已给出回复。"
                await self._send_json(websocket, {
                    "type": "thinking",
                    "step": "summary",
                    "content": summary_text,
                    "timestamp": datetime.now().isoformat(),
                })
            
        except Exception as e:
            logger.error(f"❌ 处理消息失败: {e}", exc_info=True)
            await self._send_json(websocket, {
                "type": "error",
                "code": 1007,
                "message": f"处理消息失败: {str(e)}"
            })
    
    async def _stream_agent_response(
        self,
        agent: TYMemoryAgent,
        messages: List[Dict],
        deep_thinking: bool = False,
        plan_result: Optional[Dict[str, Any]] = None,
    ):
        """
        流式调用Agent并yield响应。
        若传入 plan_result（深度思考规划），会将其注入到当前用户消息中，使执行按规划进行（ReAct 式）。
        
        Args:
            agent: TY Memory Agent实例
            messages: 历史消息
            deep_thinking: 是否启用深度思考
            plan_result: 规划结果 {"plan_text": str, "steps": [...]}，非空时会拼入最后一条用户消息，引导 Agent 按规划执行
        Yields:
            响应chunk
        """
        try:
            # 深拷贝，避免修改调用方传入的 messages
            messages = [{"role": m["role"], "content": m["content"]} for m in messages]
            if plan_result and plan_result.get("plan_text") and plan_result.get("steps"):
                # 将规划说明 + 各步骤详情注入到当前用户消息末尾，使 Agent 按规划执行（ReAct 串联）
                steps_lines = "\n".join(
                    f"  第{i}步（{s.get('type','tool')}）：{s.get('desc','')}"
                    for i, s in enumerate(plan_result["steps"], start=1)
                )
                plan_block = (
                    f"\n\n【本回合执行规划】\n{plan_result['plan_text']}\n"
                    f"具体步骤如下：\n{steps_lines}\n"
                    "请严格按上述步骤顺序执行，每一步完成后再进行下一步。"
                )
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i].get("role") == "user":
                        messages[i] = {"role": "user", "content": messages[i]["content"] + plan_block}
                        break
            qwen_messages = [
                Message(role=msg["role"], content=msg["content"])
                for msg in messages
            ]
            
            # 调用agent.run进行流式响应
            prev_content = ""
            stream = agent.run(messages=qwen_messages, stream=True)
            while True:
                await asyncio.sleep(0)  # 让出事件循环，使主循环能收到 interrupt 并 cancel 本任务
                try:
                    response = next(stream)
                except StopIteration:
                    break
                if not response:
                    continue
                
                # 获取最新消息
                if len(response) > 0:
                    last_msg = response[-1]
                    
                    # 检查是否是工具调用
                    if hasattr(last_msg, 'function_call') and last_msg.function_call:
                        yield {
                            "type": "tool_call",
                            "tool_name": last_msg.function_call.name,
                            "tool_args": last_msg.function_call.arguments
                        }
                        continue
                    
                    # 处理 FUNCTION 角色的工具返回结果
                    from qwen_agent.llm.schema import ASSISTANT, FUNCTION
                    if hasattr(last_msg, 'role') and last_msg.role == FUNCTION:
                        tool_name = getattr(last_msg, 'name', 'unknown_tool')
                        tool_result = last_msg.content
                        # 用于 cancel 等从参数取 eventId：回溯最近一次同名工具调用的 arguments
                        tool_args = None
                        if len(response) >= 2:
                            for i in range(len(response) - 1, -1, -1):
                                prev = response[i]
                                if hasattr(prev, 'function_call') and getattr(prev, 'function_call', None):
                                    if getattr(prev.function_call, 'name', None) == tool_name:
                                        tool_args = getattr(prev.function_call, 'arguments', None)
                                        break
                        yield {
                            "type": "tool_result",
                            "tool_name": tool_name,
                            "result": tool_result,
                            "tool_args": tool_args,
                        }
                        continue
                    
                    # 普通文本响应（ASSISTANT 角色）
                    current_content = last_msg.content
                    
                    # 过滤掉看起来像 JSON 数据的内容（工具返回结果可能被包含在响应中）
                    if current_content:
                        # 检查是否包含工具返回的 JSON 数据（通常以 ":[{" 或类似格式开头）
                        # 如果包含，只取 JSON 之前的部分
                        json_start_patterns = [
                            '":[{"',      # 最常见的格式
                            '":[ {',      # 带空格
                            '":[{',       # 不带引号
                            '":[{',       # 另一种格式
                        ]
                        for pattern in json_start_patterns:
                            if pattern in current_content:
                                # 找到 JSON 开始位置，只取之前的内容
                                json_pos = current_content.find(pattern)
                                # 向前查找，找到完整的句子结束位置
                                before_json = current_content[:json_pos].strip()
                                # 如果过滤后的内容为空或太短，可能是误判，保留原内容
                                if len(before_json) > 10:
                                    current_content = before_json
                                break
                    
                    # 计算增量（只基于过滤后的内容）
                    if current_content and len(current_content) > len(prev_content):
                        delta = current_content[len(prev_content):]
                        prev_content = current_content
                        
                        if delta and delta.strip():  # 只发送非空增量
                            yield {
                                "type": "delta",
                                "content": delta
                            }
            
            # TODO: 提取富媒体卡片信息（从工具调用结果中）
            # 这部分需要根据实际的工具返回格式来实现
            
        except Exception as e:
            logger.error(f"❌ Agent响应流异常: {e}", exc_info=True)
            yield {
                "type": "error",
                "message": str(e)
            }
    
    def _prepare_history_messages(self, session: SessionWrapper) -> List[Dict]:
        """
        准备历史消息
        
        Args:
            session: 会话
            
        Returns:
            消息列表
        """
        messages = []
        
        # 取最近20条消息
        recent_messages = session.messages[-20:] if len(session.messages) > 20 else session.messages
        
        for msg in recent_messages:
            messages.append({
                "role": msg.role,
                "content": msg.content
            })
        
        return messages
    
    def _is_sentence_complete(self, text: str) -> bool:
        """
        判断句子是否完成
        
        使用简单规则判断（更复杂的可以使用sentence_splitter）
        
        Args:
            text: 文本
            
        Returns:
            是否完成
        """
        if not text:
            return False
        
        # 检查是否以句号、问号、感叹号结尾
        text = text.strip()
        if not text:
            return False
        
        # 句子结束标记
        sentence_endings = ['。', '！', '？', '!', '?', '.', ';', '；']
        
        # 检查最后一个字符
        if text[-1] in sentence_endings:
            # 额外检查：如果是点号，确保不是小数点
            if text[-1] == '.':
                if len(text) >= 2 and text[-2].isdigit():
                    return False  # 可能是小数点
            return True
        
        return False

    async def _emit_message_delta_for_sentence(self, websocket: WebSocket, sentence: str) -> None:
        """
        协议约定：凡要发送 sentence_complete/语音 的句子，必须先通过 message_delta 输出，
        供客户端做字幕/流式展示。服务端注入的句子在发 sentence_complete 前必须调用本方法。
        """
        if not sentence or not sentence.strip():
            return
        await self._send_json(websocket, {
            "type": "message_delta",
            "content": sentence.strip(),
            "timestamp": datetime.now().isoformat(),
        })

    def _is_meaningful_tts_sentence(self, text: str) -> bool:
        """
        判断文本是否值得做 TTS 播报，过滤无意义片段（如 ".."、单独标点等）。
        """
        if not text or not text.strip():
            return False
        s = text.strip()
        if len(s) <= 1:
            return False
        # 仅包含省略号、点、换行等
        stripped = s.replace(".", "").replace("。", "").replace("…", "").replace("\n", "").replace(" ", "")
        if not stripped:
            return False
        # 仅标点、无实质内容（无汉字、无字母、无数字）
        import re
        if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", s):
            return False
        return True

    def _get_ride_confirm_tts_text(
        self,
        fragment: str,
        origin: Optional[str],
        destination: Optional[str],
    ) -> Optional[str]:
        """
        若 fragment 是叫车确认场景的残句（如「车型。」）或整段以该残句结尾，返回应播报的完整句；
        否则返回 None 表示不替换。
        """
        if not fragment or not fragment.strip():
            return None
        s = fragment.strip()
        # 残句特征：很短且含「车型」，或整段以「车型。」/「选择一种车型。」结尾
        is_ride_fragment = (
            (len(s) <= 12 and "车型" in s)
            or s.endswith("车型。")
            or s.endswith("选择一种车型。")
        )
        if is_ride_fragment:
            if origin and destination:
                return f"起点是{origin}，终点是{destination}，已为您查询到几种车型与预估价格，请确认起终点无误后选择一种车型。"
            return "已为您查询到几种车型与预估价格，请确认起终点无误后选择一种车型。"
        return None
    
    def _is_ride_confirm_message(self, message: str) -> bool:
        """判断用户消息是否为「确认叫车」信息（含起点/终点/车型/电话等）。"""
        if not message or not message.strip():
            return False
        import re
        s = message.strip()
        has_origin_dest = "起点" in s or "终点" in s
        vehicle_keywords = ("车型", "豪华车", "专车", "快车", "特惠快车")
        has_vehicle = any(k in s for k in vehicle_keywords)
        has_phone = bool(re.search(r"1[3-9]\d{9}", s)) or "电话" in s
        return (has_origin_dest and has_vehicle) or (has_vehicle and has_phone)
    
    def _parse_ride_confirm_from_message(self, message: str) -> Tuple[Optional[int], Optional[str]]:
        """
        从确认叫车消息中解析 product_category 和 phone。
        车型映射：豪华车->17, 专车->8, 快车->1, 特惠快车->201。
        """
        import re
        product_category = None
        for name, code in [("豪华车", 17), ("专车", 8), ("快车", 1), ("特惠快车", 201)]:
            if name in message:
                product_category = code
                break
        phone = None
        m = re.search(r"1[3-9]\d{9}", message)
        if m:
            phone = m.group(0)
        return (product_category, phone)
    
    async def _handle_ride_confirm_and_create_order(
        self,
        websocket: WebSocket,
        session_id: str,
        user_id: int,
        user_message: str,
        pending_ride: Dict[str, Any],
        enable_tts: bool,
        tts_config: Optional[TTSConfig],
    ) -> bool:
        """
        用户确认叫车后直接调用 taxi_create_order，不经过 Agent。
        成功则发送 tool_result、订单卡片、启动司机轮询、TTS、保存助手消息并发送 done；清除 pending_ride。
        返回 True 表示已处理并应跳过 Agent；False 表示未处理（如参数缺失）。
        """
        from ty_mem_agent.mcp_integrations.tool_registry import get_tool_registry
        from ty_mem_agent.server.rich_card_manager import (
            build_ride_hailing_cards_from_didi_result,
            get_rich_card_manager,
        )
        estimate_flow_id = pending_ride.get("estimate_flow_id")
        if not estimate_flow_id:
            logger.warning("⚠️ pending_ride 缺少 estimate_flow_id，跳过直接叫车")
            return False
        estimate_trace_id = pending_ride.get("estimate_trace_id") or estimate_flow_id
        product_category, phone_from_msg = self._parse_ride_confirm_from_message(user_message)
        if product_category is None:
            logger.warning("⚠️ 无法从消息中解析车型，跳过直接叫车")
            return False
        phone = phone_from_msg or pending_ride.get("user_phone")
        if not phone:
            logger.warning("⚠️ 缺少电话号码，跳过直接叫车")
            return False
        # MCP 要求参数为字符串类型（与 taxi_estimate 一致），且 create_order 必填 estimate_trace_id（无则复用 estimate_flow_id）
        def _str(v):
            return str(v) if v is not None else ""
        create_params = {
            "estimate_flow_id": _str(estimate_flow_id),
            "estimate_trace_id": _str(estimate_trace_id),
            "product_category": _str(product_category),
            "from_lng": _str(pending_ride.get("from_lng")),
            "from_lat": _str(pending_ride.get("from_lat")),
            "from_name": _str(pending_ride.get("from_name")),
            "to_lng": _str(pending_ride.get("to_lng")),
            "to_lat": _str(pending_ride.get("to_lat")),
            "to_name": _str(pending_ride.get("to_name")),
            "phone": _str(phone),
        }
        registry = get_tool_registry()
        all_tools = registry.get_all_tools()
        create_tool = None
        for t in all_tools:
            if getattr(t, "name", "") == "Didi-Ride-taxi_create_order":
                create_tool = t
                break
        if not create_tool:
            logger.warning("⚠️ 未找到 Didi-Ride-taxi_create_order，跳过直接叫车")
            return False
        await self._send_json(websocket, {
            "type": "generation_started",
            "timestamp": datetime.now().isoformat(),
        })
        params_str = json.dumps(create_params, ensure_ascii=False)
        try:
            create_result = await asyncio.to_thread(create_tool.call, params_str)
        except Exception as e:
            logger.error(f"❌ 直接调用 taxi_create_order 失败: {e}", exc_info=True)
            await self._send_json(websocket, {
                "type": "tool_result",
                "tool_name": "Didi-Ride-taxi_create_order",
                "result": f"叫车失败: {str(e)}",
                "timestamp": datetime.now().isoformat(),
            })
            self.chat_manager.clear_pending_ride(session_id)
            final_content = f"叫车失败：{str(e)}"
            self.chat_manager.add_message(session_id=session_id, role="assistant", content=final_content)
            await self._send_json(websocket, {
                "type": "done",
                "message_id": None,
                "full_content": final_content,
                "total_audio_duration_ms": 0,
                "timestamp": datetime.now().isoformat(),
            })
            return True
        result_for_extract = (
            str(create_result) if not isinstance(create_result, (dict, list)) else create_result
        )
        await self._send_json(websocket, {
            "type": "tool_result",
            "tool_name": "Didi-Ride-taxi_create_order",
            "result": create_result,
            "timestamp": datetime.now().isoformat(),
        })
        ride_cards = build_ride_hailing_cards_from_didi_result(
            tool_name="Didi-Ride-taxi_create_order",
            tool_result=result_for_extract,
            user_id=user_id,
            tool_args=create_params,
        )
        card_manager = get_rich_card_manager()
        if ride_cards:
            for card in ride_cards:
                try:
                    card_manager.create_card(
                        event_id=0,
                        user_id=user_id,
                        card_type=card.get("card_type", "ride_hailing"),
                        title=card.get("title", "打车信息"),
                        subtitle=card.get("subtitle"),
                        icon=card.get("icon"),
                        data=card.get("data", {}),
                        source=card.get("source", "通用聊天-滴滴打车"),
                        expires_at=card.get("expires_at"),
                        card_id=card.get("card_id"),
                    )
                    self.chat_manager.add_card_to_session(session_id=session_id, card=card)
                    await self._send_json(websocket, {
                        "type": "rich_card",
                        "card_id": card.get("card_id"),
                        "card_type": card.get("card_type"),
                        "title": card.get("title"),
                        "subtitle": card.get("subtitle"),
                        "icon": card.get("icon"),
                        "data": card.get("data", {}),
                        "source": card.get("source"),
                        "created_at": card.get("created_at"),
                        "updated_at": card.get("updated_at"),
                        "expires_at": card.get("expires_at"),
                        "timestamp": datetime.now().isoformat(),
                    })
                    logger.info(f"🎴 打车卡片已创建并推送: {card.get('card_type')} - {card.get('title')}")
                    data = card.get("data") or {}
                    if data.get("stage") == "success" and data.get("order_id"):
                        self.chat_manager.set_last_ride_order_id(session_id, data["order_id"])
                        asyncio.create_task(self._poll_ride_order_until_driver(
                            websocket=websocket,
                            session_id=session_id,
                            user_id=user_id,
                            order_id=data["order_id"],
                            enable_tts=enable_tts,
                            tts_config=tts_config,
                        ))
                        break
                except Exception as e:
                    logger.warning(f"⚠️ 打车卡片创建失败: {e}")
        self.chat_manager.clear_pending_ride(session_id)
        tts_text = "已为您叫车，请稍候。"
        await self._emit_message_delta_for_sentence(websocket, tts_text)
        await self._send_json(websocket, {
            "type": "sentence_complete",
            "sentence": tts_text,
            "timestamp": datetime.now().isoformat(),
        })
        if enable_tts and tts_config:
            await self._generate_and_send_audio(
                websocket=websocket,
                text=tts_text,
                tts_config=tts_config,
            )
        rich_cards = self.chat_manager.get_session_cards(session_id) or []
        ai_msg = self.chat_manager.add_message(
            session_id=session_id,
            role="assistant",
            content=tts_text,
            rich_cards=rich_cards,
        )
        await self._send_json(websocket, {
            "type": "done",
            "message_id": ai_msg.message_id if ai_msg else None,
            "full_content": tts_text,
            "total_audio_duration_ms": 0,
            "timestamp": datetime.now().isoformat(),
        })
        logger.info("✅ 打车确认已处理：已直接调用 taxi_create_order 并完成推送")
        return True
    
    def _is_ride_cancel_message(self, message: str) -> bool:
        """判断用户消息是否为「取消叫车/取消订单」意图"""
        if not message or not message.strip():
            return False
        s = message.strip()
        cancel_keywords = ("取消", "不叫车", "不要叫车", "不用叫车", "取消订单", "取消叫车", "取消这个订单", "取消这个叫车")
        return any(k in s for k in cancel_keywords)
    
    async def _handle_ride_cancel_and_call_mcp(
        self,
        websocket: WebSocket,
        session_id: str,
        user_id: int,
        order_id: str,
        enable_tts: bool,
        tts_config: Optional[TTSConfig],
    ) -> bool:
        """
        用户要求取消订单时直接调用 Didi-Ride-taxi_cancel_order，不经过 Agent。
        成功则清除 session_last_ride_order_id，发送 TTS 与 done；失败则提示错误。
        """
        from ty_mem_agent.mcp_integrations.tool_registry import get_tool_registry
        registry = get_tool_registry()
        all_tools = registry.get_all_tools()
        cancel_tool = None
        for t in all_tools:
            if getattr(t, "name", "") == "Didi-Ride-taxi_cancel_order":
                cancel_tool = t
                break
        if not cancel_tool:
            logger.warning("⚠️ 未找到 Didi-Ride-taxi_cancel_order，无法直接取消订单")
            return False
        await self._send_json(websocket, {
            "type": "generation_started",
            "timestamp": datetime.now().isoformat(),
        })
        params_str = json.dumps({"order_id": order_id}, ensure_ascii=False)
        try:
            cancel_result = await asyncio.to_thread(cancel_tool.call, params_str)
        except Exception as e:
            logger.error(f"❌ 直接调用 taxi_cancel_order 失败: {e}", exc_info=True)
            await self._send_cancel_result_and_done(
                websocket, session_id, f"取消订单失败：{str(e)}", enable_tts, tts_config
            )
            return True
        result_text = str(cancel_result) if not isinstance(cancel_result, (dict, list)) else json.dumps(cancel_result, ensure_ascii=False)
        await self._send_json(websocket, {
            "type": "tool_result",
            "tool_name": "Didi-Ride-taxi_cancel_order",
            "result": cancel_result,
            "timestamp": datetime.now().isoformat(),
        })
        success = "取消成功" in result_text or "已取消" in result_text
        if success:
            self.chat_manager.clear_last_ride_order_id(session_id)
            tts_text = "已为您取消叫车订单。"
        else:
            tts_text = result_text if len(result_text) < 80 else "取消订单失败，请稍后重试或联系客服。"
        await self._send_cancel_result_and_done(websocket, session_id, tts_text, enable_tts, tts_config)
        logger.info("✅ 取消订单已处理：已直接调用 taxi_cancel_order")
        return True
    
    async def _send_cancel_result_and_done(
        self,
        websocket: WebSocket,
        session_id: str,
        content: str,
        enable_tts: bool,
        tts_config: Optional[TTSConfig],
    ) -> None:
        """发送取消订单后的文案流（message_delta + sentence_complete）、可选 TTS、助手消息和 done 事件"""
        await self._emit_message_delta_for_sentence(websocket, content)
        await self._send_json(websocket, {
            "type": "sentence_complete",
            "sentence": content,
            "timestamp": datetime.now().isoformat(),
        })
        if enable_tts and tts_config:
            await self._generate_and_send_audio(websocket=websocket, text=content, tts_config=tts_config)
        rich_cards = self.chat_manager.get_session_cards(session_id) or []
        ai_msg = self.chat_manager.add_message(
            session_id=session_id,
            role="assistant",
            content=content,
            rich_cards=rich_cards,
        )
        await self._send_json(websocket, {
            "type": "done",
            "message_id": ai_msg.message_id if ai_msg else None,
            "full_content": content,
            "total_audio_duration_ms": 0,
            "timestamp": datetime.now().isoformat(),
        })

    async def _poll_ride_order_until_driver(
        self,
        websocket: WebSocket,
        session_id: str,
        user_id: int,
        order_id: str,
        enable_tts: bool = False,
        tts_config: Optional[TTSConfig] = None,
        poll_interval_sec: float = 3.0,
        max_polls: int = 20,
    ):
        """
        订单创建成功后，后台轮询 taxi_query_order；司机接单后推送「司机已接单」卡片并可选 TTS。
        """
        from ty_mem_agent.mcp_integrations.tool_registry import get_tool_registry
        from ty_mem_agent.server.rich_card_manager import (
            build_driver_card_from_query_result,
            get_rich_card_manager,
        )
        registry = get_tool_registry()
        all_tools = registry.get_all_tools()
        query_tool = None
        for t in all_tools:
            if getattr(t, "name", "") == "Didi-Ride-taxi_query_order":
                query_tool = t
                break
        if not query_tool:
            logger.debug("未找到 Didi-Ride-taxi_query_order，跳过订单状态轮询")
            return
        params = json.dumps({"order_id": order_id})
        for _ in range(max_polls):
            await asyncio.sleep(poll_interval_sec)
            try:
                result = await asyncio.to_thread(query_tool.call, params)
            except Exception as e:
                logger.debug(f"轮询订单状态失败: {e}")
                continue
            driver_card = build_driver_card_from_query_result(order_id=order_id, query_result=result)
            if not driver_card:
                continue
            try:
                card_manager = get_rich_card_manager()
                card_manager.create_card(
                    event_id=0,
                    user_id=user_id,
                    card_type=driver_card.get("card_type", "ride_hailing"),
                    title=driver_card.get("title", "司机已接单"),
                    subtitle=driver_card.get("subtitle"),
                    icon=driver_card.get("icon"),
                    data=driver_card.get("data", {}),
                    source=driver_card.get("source", ""),
                    expires_at=driver_card.get("expires_at"),
                    card_id=driver_card.get("card_id"),
                )
                self.chat_manager.add_card_to_session(session_id=session_id, card=driver_card)
                await self._send_json(websocket, {
                    "type": "rich_card",
                    "card_id": driver_card.get("card_id"),
                    "card_type": driver_card.get("card_type"),
                    "title": driver_card.get("title"),
                    "subtitle": driver_card.get("subtitle"),
                    "icon": driver_card.get("icon"),
                    "data": driver_card.get("data", {}),
                    "source": driver_card.get("source"),
                    "created_at": driver_card.get("created_at"),
                    "updated_at": driver_card.get("updated_at"),
                    "expires_at": driver_card.get("expires_at"),
                    "timestamp": datetime.now().isoformat(),
                })
                logger.info("🎴 司机已接单卡片已推送")
                d = driver_card.get("data") or {}
                tts_text = f"司机已接单。"
                if d.get("driver_name"):
                    tts_text += f"司机{d.get('driver_name')}。"
                if d.get("car_plate"):
                    tts_text += f"车牌{d.get('car_plate')}。"
                if tts_text:
                    await self._emit_message_delta_for_sentence(websocket, tts_text)
                    await self._send_json(websocket, {
                        "type": "sentence_complete",
                        "sentence": tts_text,
                        "timestamp": datetime.now().isoformat(),
                    })
                if enable_tts and tts_text:
                    await self._generate_and_send_audio(websocket, tts_text, tts_config)
            except Exception as e:
                logger.warning(f"推送司机接单卡片或 TTS 失败: {e}")
            break
        logger.debug(f"订单 {order_id} 轮询 {max_polls} 次后未获取到司机信息，停止轮询")
    
    async def _generate_and_send_audio(
        self,
        websocket: WebSocket,
        text: str,
        tts_config: Optional[TTSConfig] = None
    ):
        """
        生成并发送TTS音频
        
        Args:
            websocket: WebSocket连接
            text: 要合成的文本
            tts_config: TTS配置
        """
        if not text or not text.strip():
            return
        
        # TTS API 限制：文本长度必须在 0-600 字符之间
        MAX_TTS_LENGTH = 600
        text = text.strip()
        
        if len(text) > MAX_TTS_LENGTH:
            logger.warning(f"⚠️ TTS文本长度 {len(text)} 超过限制 {MAX_TTS_LENGTH}，跳过TTS")
            return
        
        try:
            # 发送音频开始事件（包含PCM格式参数）
            await self._send_json(websocket, {
                "type": "audio_start",
                "text": text,
                "audio_format": {
                    "format": "pcm",  # PCM原始格式
                    "sample_rate": 24000,  # 24kHz采样率
                    "bit_depth": 16,  # 16bit位深
                    "channels": 1,  # 单声道
                    "encoding": "pcm_s16le"  # signed 16-bit little-endian
                },
                "timestamp": datetime.now().isoformat()
            })
            
            # 流式生成音频
            total_bytes = 0
            async for audio_chunk in self.tts_service.synthesize_stream(text, tts_config):
                # 发送二进制音频数据
                await websocket.send_bytes(audio_chunk)
                total_bytes += len(audio_chunk)
            
            # 发送音频结束事件
            await self._send_json(websocket, {
                "type": "audio_end",
                "total_bytes": total_bytes,
                "timestamp": datetime.now().isoformat()
            })
            
            logger.debug(f"✅ TTS音频发送完成: text_len={len(text)}, audio_bytes={total_bytes}")
            
        except Exception as e:
            logger.error(f"❌ TTS音频生成失败: {e}")
            await self._send_json(websocket, {
                "type": "error",
                "code": 2001,
                "message": f"TTS音频生成失败: {str(e)}"
            })
    
    async def _send_title_when_ready(
        self,
        websocket: WebSocket,
        session_id: str,
        user_message: str
    ):
        """
        在后台生成标题，就绪后更新会话并推送 title_updated。
        与 Agent 流式处理并发执行，便于 APP 尽早展示会话标题。
        """
        try:
            title = await self._generate_session_title(
                user_message=user_message,
                ai_response=""  # 早发标题仅基于用户输入，不等待 AI 回复
            )
            if title:
                self.chat_manager.update_session_title(session_id, title)
                await self._send_json(websocket, {
                    "type": "title_updated",
                    "session_id": session_id,
                    "title": title,
                    "timestamp": datetime.now().isoformat()
                })
                logger.debug(f"📌 已并发生成并推送标题: session_id={session_id}, title={title}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"⚠️ 并发生成标题失败: {e}")
    
    def _generate_session_title_sync(self, user_message: str) -> Optional[str]:
        """
        同步调用 LLM 生成会话标题（供 to_thread 使用）。
        参考 chat_server 与项目内 get_chat_model 用法。
        """
        try:
            from ty_mem_agent.config.settings import get_llm_config, settings
            from qwen_agent.llm import get_chat_model

            if not getattr(settings, "DASHSCOPE_API_KEY", None) and not getattr(settings, "OPENAI_API_KEY", None):
                logger.warning("⚠️ 未配置 LLM API 密钥，使用简化标题")
                return self._fallback_title(user_message)

            llm_config = get_llm_config()
            llm = get_chat_model(llm_config)

            prompt = f"""请根据用户的第一条消息，生成一个简洁的对话标题（不超过20个字）。

用户消息：{user_message}

要求：
1. 标题要简洁明了，能概括对话主题
2. 不要包含标点符号
3. 不要添加引号或其他修饰
4. 直接输出标题内容，不要有任何前缀或后缀

标题："""

            messages = [Message(role=USER, content=prompt)]
            response = None
            for chunk in llm.chat(messages=messages, stream=True):
                response = chunk

            if response and len(response) > 0:
                last = response[-1]
                content = getattr(last, "content", None) if hasattr(last, "content") else (last if isinstance(last, str) else "")
                title = (content or "").strip() if isinstance(content, str) else str(content or "").strip()
                title = title.replace('"', '').replace("'", '').replace('：', '').replace(':', '')
                title = title.replace('标题', '').strip()
                if len(title) > 30:
                    title = title[:30].rstrip() + "..."
                if title:
                    logger.debug(f"✅ LLM 生成标题: {title}")
                    return title
            logger.warning("⚠️ LLM 返回空响应，使用简化标题")
            return self._fallback_title(user_message)
        except Exception as e:
            logger.warning(f"⚠️ LLM 生成标题失败: {e}，使用简化标题")
            return self._fallback_title(user_message)

    @staticmethod
    def _fallback_title(user_message: str) -> str:
        """无 LLM 或失败时的兜底标题：用户消息前 15 字"""
        u = (user_message or "").strip()
        if len(u) <= 15:
            return u or "新对话"
        return u[:15] + "..."

    async def _generate_session_title(
        self,
        user_message: str,
        ai_response: str
    ) -> Optional[str]:
        """
        生成会话标题（优先 LLM，兜底为规则）。
        早发标题时仅用 user_message，不依赖 ai_response。
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._generate_session_title_sync(user_message or "")
        )
    
    async def _send_json(self, websocket: WebSocket, data: Dict):
        """
        发送JSON消息
        
        Args:
            websocket: WebSocket连接
            data: 数据
        """
        try:
            await websocket.send_json(data)
        except WebSocketDisconnect:
            # 连接已断开，直接重新抛出
            raise
        except Exception as e:
            # 检查是否是连接已断开的错误（通过错误消息判断）
            error_str = str(e).lower()
            disconnect_keywords = ["disconnect", "close", "response already completed"]
            if any(keyword in error_str for keyword in disconnect_keywords):
                # 转换为 WebSocketDisconnect 以便上层统一处理
                raise WebSocketDisconnect(code=1006)
            # 其他错误记录日志并重新抛出
            logger.error(f"❌ 发送JSON消息失败: {e}")
            raise


# 全局单例
_general_chat_ws_service = None


def get_general_chat_websocket_service() -> GeneralChatWebSocketService:
    """获取通用聊天WebSocket服务单例"""
    global _general_chat_ws_service
    if _general_chat_ws_service is None:
        _general_chat_ws_service = GeneralChatWebSocketService()
    return _general_chat_ws_service

