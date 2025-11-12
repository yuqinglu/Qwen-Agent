#!/usr/bin/env python3
"""
聊天服务器
基于FastAPI的多用户聊天服务，集成TY Memory Agent
"""

import asyncio
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from loguru import logger

# 使用简洁的绝对导入
from ty_mem_agent.config.settings import settings
from ty_mem_agent.agents.ty_memory_agent import TYMemoryAgent
from ty_mem_agent.memory.user_memory import get_integrated_memory
from ty_mem_agent.server.user_manager import user_manager, init_default_users
from ty_mem_agent.server.conversation_manager import get_conversation_manager
from qwen_agent.llm.schema import Message, USER, ASSISTANT


# Pydantic模型
class UserLogin(BaseModel):
    username: str
    password: str


class UserRegister(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


class ChatMessage(BaseModel):
    content: str
    message_type: str = "text"
    timestamp: Optional[datetime] = None


class ChatResponse(BaseModel):
    message: str
    timestamp: datetime
    message_id: str
    metadata: Optional[Dict] = None


class CreateConversationRequest(BaseModel):
    title: Optional[str] = "新对话"


class UpdateConversationTitleRequest(BaseModel):
    title: str


# 安全相关
security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """获取当前用户"""
    token = credentials.credentials
    user_id = user_manager.verify_access_token(token)
    
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = user_manager.get_user(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    return user


class ChatServer:
    """聊天服务器"""
    
    def __init__(self):
        self.app = FastAPI(
            title="TY Memory Agent Chat Server",
            description="智能记忆助手聊天服务",
            version="1.0.0"
        )
        
        # CORS配置
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # 生产环境应限制具体域名
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # WebSocket连接管理
        self.active_connections: Dict[str, WebSocket] = {}
        self.user_agents: Dict[str, TYMemoryAgent] = {}
        self.agent_last_used: Dict[str, datetime] = {}  # user_id -> 最后使用时间
        self.agent_creation_locks: Dict[str, asyncio.Lock] = {}  # user_id -> 创建锁，防止并发创建
        
        # 会话管理器
        self.conversation_manager = get_conversation_manager()
        
        # 用户当前会话追踪
        self.user_current_conversation: Dict[str, str] = {}  # user_id -> conversation_id
        
        # Agent过期时间（秒）- 30分钟未使用才删除
        self.agent_idle_timeout = 30 * 60  # 30分钟
        
        # 初始化路由
        self._setup_routes()
        
        # 注册待办API路由
        self._register_todo_routes()
        
        # 初始化默认用户
        init_default_users()
        
        logger.info("🚀 Chat Server 初始化完成")
    
    def _setup_routes(self):
        """设置路由"""
        
        @self.app.get("/")
        async def root():
            """首页"""
            return {"message": "TY Memory Agent Chat Server", "version": "1.0.0"}
        
        @self.app.get("/health")
        async def health_check():
            """健康检查"""
            return {
                "status": "healthy",
                "timestamp": datetime.now(),
                "users": user_manager.get_user_stats()
            }
        
        @self.app.post("/auth/register")
        async def register(user_data: UserRegister):
            """用户注册"""
            user = user_manager.create_user(
                username=user_data.username,
                password=user_data.password,
                email=user_data.email
            )
            
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="用户名已存在或注册失败"
                )
            
            return {"message": "注册成功", "user_id": user.user_id}
        
        @self.app.post("/auth/login")
        async def login(login_data: UserLogin):
            """用户登录"""
            user = user_manager.authenticate_user(
                username=login_data.username,
                password=login_data.password
            )
            
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="用户名或密码错误"
                )
            
            # 创建会话和令牌
            session = user_manager.create_session(user.user_id)
            token = user_manager.create_access_token(user.user_id)
            
            return {
                "access_token": token,
                "token_type": "bearer",
                "user_id": user.user_id,
                "username": user.username,
                "session_id": session.session_id if session else None
            }
        
        @self.app.post("/auth/logout")
        async def logout(current_user = Depends(get_current_user)):
            """用户登出"""
            # 结束用户会话
            session = user_manager.get_user_session(current_user.user_id)
            if session:
                user_manager.end_session(session.session_id)
            
            # 断开WebSocket连接
            if current_user.user_id in self.active_connections:
                await self._disconnect_user(current_user.user_id)
            
            return {"message": "登出成功"}
        
        @self.app.get("/user/profile")
        async def get_profile(current_user = Depends(get_current_user)):
            """获取用户资料"""
            # 获取用户记忆摘要
            memory_summary = await self._get_user_memory_summary(current_user.user_id)
            
            return {
                "user_id": current_user.user_id,
                "username": current_user.username,
                "email": current_user.email,
                "created_at": current_user.created_at,
                "last_login": current_user.last_login,
                "memory_summary": memory_summary
            }
        
        @self.app.get("/user/stats")
        async def get_user_stats(current_user = Depends(get_current_user)):
            """获取用户统计信息"""
            return user_manager.get_user_stats()
        
        @self.app.websocket("/ws/{token}")
        async def websocket_endpoint(websocket: WebSocket, token: str):
            """WebSocket聊天端点"""
            # 验证令牌
            user_id = user_manager.verify_access_token(token)
            if not user_id:
                await websocket.close(code=4001, reason="Invalid token")
                return
            
            user = user_manager.get_user(user_id)
            if not user:
                await websocket.close(code=4002, reason="User not found")
                return
            
            await self._handle_websocket_connection(websocket, user)
        
        @self.app.get("/chat/demo")
        async def chat_demo():
            """聊天演示页面"""
            # 从外部文件读取HTML
            html_path = Path(__file__).parent / "templates" / "chat_demo.html"
            if html_path.exists():
                with open(html_path, 'r', encoding='utf-8') as f:
                    return HTMLResponse(f.read())
            else:
                return HTMLResponse("<h1>聊天页面模板未找到</h1>", status_code=404)
        
        # ==================== 会话管理API ====================
        
        @self.app.get("/conversations")
        async def get_conversations(current_user = Depends(get_current_user)):
            """获取用户的所有会话列表"""
            try:
                conversations = self.conversation_manager.get_user_conversations(
                    user_id=current_user.user_id,
                    limit=50
                )
                return {
                    "conversations": conversations,
                    "total": len(conversations)
                }
            except Exception as e:
                logger.error(f"获取会话列表失败: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=str(e)
                )
        
        @self.app.post("/conversations")
        async def create_conversation(
            request: CreateConversationRequest,
            current_user = Depends(get_current_user)
        ):
            """创建新会话"""
            try:
                conversation = self.conversation_manager.create_conversation(
                    user_id=current_user.user_id,
                    title=request.title
                )
                
                # 设置为当前会话
                self.user_current_conversation[current_user.user_id] = conversation.conversation_id
                
                return {
                    "conversation_id": conversation.conversation_id,
                    "title": conversation.title,
                    "created_at": conversation.created_at
                }
            except Exception as e:
                logger.error(f"创建会话失败: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=str(e)
                )
        
        @self.app.get("/conversations/{conversation_id}")
        async def get_conversation(
            conversation_id: str,
            current_user = Depends(get_current_user)
        ):
            """获取指定会话的详细信息"""
            try:
                conversation = self.conversation_manager.get_conversation(conversation_id)
                
                if not conversation:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="会话不存在"
                    )
                
                # 验证会话所有权
                if conversation.user_id != current_user.user_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="无权访问此会话"
                    )
                
                return conversation.to_dict()
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"获取会话失败: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=str(e)
                )
        
        @self.app.get("/conversations/{conversation_id}/messages")
        async def get_conversation_messages(
            conversation_id: str,
            current_user = Depends(get_current_user)
        ):
            """获取指定会话的所有消息"""
            try:
                conversation = self.conversation_manager.get_conversation(conversation_id)
                
                if not conversation:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="会话不存在"
                    )
                
                # 验证会话所有权
                if conversation.user_id != current_user.user_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="无权访问此会话"
                    )
                
                messages = self.conversation_manager.get_conversation_messages(conversation_id)
                return {
                    "conversation_id": conversation_id,
                    "messages": messages,
                    "total": len(messages)
                }
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"获取会话消息失败: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=str(e)
                )
        
        @self.app.put("/conversations/{conversation_id}/title")
        async def update_conversation_title(
            conversation_id: str,
            request: UpdateConversationTitleRequest,
            current_user = Depends(get_current_user)
        ):
            """更新会话标题"""
            try:
                conversation = self.conversation_manager.get_conversation(conversation_id)
                
                if not conversation:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="会话不存在"
                    )
                
                # 验证会话所有权
                if conversation.user_id != current_user.user_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="无权访问此会话"
                    )
                
                success = self.conversation_manager.update_conversation_title(
                    conversation_id,
                    request.title
                )
                
                if success:
                    return {"message": "标题更新成功", "title": request.title}
                else:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="标题更新失败"
                    )
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"更新会话标题失败: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=str(e)
                )
        
        @self.app.post("/conversations/{conversation_id}/generate-title")
        async def generate_conversation_title(
            conversation_id: str,
            current_user = Depends(get_current_user)
        ):
            """使用AI自动生成会话标题"""
            try:
                conversation = self.conversation_manager.get_conversation(conversation_id)
                
                if not conversation:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="会话不存在"
                    )
                
                # 验证会话所有权
                if conversation.user_id != current_user.user_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="无权访问此会话"
                    )
                
                # 获取用户的第一条消息
                user_messages = [msg for msg in conversation.messages if msg.role == 'user']
                if not user_messages:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="会话中没有用户消息"
                    )
                
                first_user_message = user_messages[0].content
                
                # 使用AI生成标题
                title = await self._generate_title_with_llm(first_user_message)
                
                # 更新标题
                self.conversation_manager.update_conversation_title(conversation_id, title)
                
                return {"title": title, "conversation_id": conversation_id}
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"生成会话标题失败: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=str(e)
                )
        
        @self.app.delete("/conversations/{conversation_id}")
        async def delete_conversation(
            conversation_id: str,
            current_user = Depends(get_current_user)
        ):
            """删除会话"""
            try:
                conversation = self.conversation_manager.get_conversation(conversation_id)
                
                if not conversation:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="会话不存在"
                    )
                
                # 验证会话所有权
                if conversation.user_id != current_user.user_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="无权访问此会话"
                    )
                
                success = self.conversation_manager.delete_conversation(conversation_id)
                
                if success:
                    return {"message": "会话删除成功"}
                else:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="会话删除失败"
                    )
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"删除会话失败: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=str(e)
                )
    
    async def _handle_websocket_connection(self, websocket: WebSocket, user):
        """处理WebSocket连接"""
        await websocket.accept()
        
        user_id = user.user_id
        self.active_connections[user_id] = websocket
        
        # 创建或获取用户的Agent（如果不存在或已过期，则创建新的）
        agent = await self._get_or_create_agent(user_id)
        if not agent:
            # Agent创建失败，记录错误但不立即断开连接
            # 允许用户重试，在发送消息时会再次尝试创建
            logger.error(f"❌ 用户连接时Agent创建失败: {user.username} ({user_id})")
            logger.warning("   将在用户发送消息时重试创建Agent")
        
        # 不自动创建会话，让用户主动选择
        # 只有在用户发送消息时才创建会话
        logger.info(f"🔗 用户连接: {user.username} ({user_id})，等待用户主动创建会话")
        
        try:
            # 发送欢迎消息
            await self._send_welcome_message(websocket, user)
            
            # 处理消息循环
            while True:
                # 接收消息
                data = await websocket.receive_text()
                message_data = json.loads(data)
                
                # 处理聊天消息
                await self._handle_chat_message(websocket, user_id, message_data)
                
        except WebSocketDisconnect:
            logger.info(f"🔌 用户断开连接: {user.username}")
        except Exception as e:
            logger.error(f"❌ WebSocket错误: {e}")
        finally:
            await self._disconnect_user(user_id)
    
    async def _send_welcome_message(self, websocket: WebSocket, user):
        """发送欢迎消息"""
        try:
            # 获取用户记忆摘要
            memory_summary = await self._get_user_memory_summary(user.user_id)
            
            welcome_parts = [f"👋 欢迎回来，{user.username}！"]
            
            if memory_summary.get("user_profile"):
                profile = memory_summary["user_profile"]
                if profile.get("location"):
                    welcome_parts.append(f"我记得您在{profile['location']}")
                if profile.get("interests"):
                    welcome_parts.append(f"您对{', '.join(profile['interests'][:2])}感兴趣")
            
            welcome_parts.append("\n🤖 我是您的智能记忆助手，可以为您：")
            welcome_parts.append("• 🌤️ 查询天气（高德）")
            welcome_parts.append("• 🕐 时间查询")
            welcome_parts.append("• 💭 记住我们的对话和您的偏好")
            
            welcome_message = "\n".join(welcome_parts)
            
            response = {
                "type": "message",
                "content": welcome_message,
                "timestamp": datetime.now().isoformat(),
                "message_id": f"welcome_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "metadata": {"type": "welcome", "memory_summary": memory_summary}
            }
            
            await websocket.send_text(json.dumps(response))
            
        except Exception as e:
            logger.error(f"❌ 发送欢迎消息失败: {e}")
    
    async def _handle_chat_message(self, websocket: WebSocket, user_id: str, message_data: Dict):
        """处理聊天消息"""
        try:
            content = message_data.get("content", "")
            if not content.strip():
                return
            
            # 获取当前会话ID
            conversation_id = message_data.get("conversation_id") or self.user_current_conversation.get(user_id)
            
            if not conversation_id:
                # 创建新会话
                conversation = self.conversation_manager.create_conversation(
                    user_id=user_id,
                    title="新对话"
                )
                conversation_id = conversation.conversation_id
                self.user_current_conversation[user_id] = conversation_id
                logger.info(f"📝 创建新会话: {conversation_id}")
            
            # 保存用户消息到会话
            self.conversation_manager.add_message(
                conversation_id=conversation_id,
                role='user',
                content=content
            )
            
            # 发送正在处理消息（使用thinking类型）
            thinking_message_id = f"thinking_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            await websocket.send_text(json.dumps({
                "type": "thinking",
                "subtype": "processing",
                "content": "💭 正在思考...",
                "timestamp": datetime.now().isoformat(),
                "message_id": thinking_message_id
            }))
            
            # 获取用户的Agent（如果不存在，自动创建）
            # 最多重试3次，每次间隔1秒
            max_retries = 3
            retry_delay = 1.0
            agent = None
            
            for attempt in range(max_retries):
                agent = await self._get_or_create_agent(user_id)
                if agent:
                    break
                
                if attempt < max_retries - 1:
                    logger.warning(f"⚠️ Agent创建失败，第 {attempt + 1} 次重试（共 {max_retries} 次）: {user_id}")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # 指数退避
            
            if not agent:
                error_msg = "Agent初始化失败，请稍后重试。如果问题持续，请联系管理员。"
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "content": error_msg,
                    "timestamp": datetime.now().isoformat(),
                    "error_code": "AGENT_INIT_FAILED"
                }))
                logger.error(f"❌ 无法为用户 {user_id} 创建Agent（已重试 {max_retries} 次）")
                return
            
            # 更新Agent最后使用时间
            self.agent_last_used[user_id] = datetime.now()
            
            # 🔧 修复：获取会话历史，构建包含上下文的消息列表
            conversation = self.conversation_manager.get_conversation(conversation_id)
            messages = []
            
            if conversation and conversation.messages:
                # 获取最近N轮对话（默认最近10条消息，约5轮对话）
                max_context_messages = 10  # 可以在settings中配置
                recent_messages = conversation.messages[-max_context_messages:]
                
                # 构建消息列表
                for msg in recent_messages:
                    messages.append(Message(
                        role=msg.role,
                        content=msg.content
                    ))
                
                logger.debug(f"📜 传递会话历史: {len(messages)} 条消息")
            else:
                # 如果没有历史，就只传当前消息
                messages = [Message(role=USER, content=content)]
                logger.debug(f"📜 无会话历史，只传递当前消息")
            
            # 处理消息并流式返回
            response_content = ""  # 累积的内容
            displayed_content = ""  # 已经显示的内容（小字）
            message_id = f"msg_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            has_tool_call = False  # 是否有工具调用
            tool_call_history = set()  # 工具调用去重
            
            # 使用run_with_memory进行带记忆的对话
            async for response in agent.run_with_memory(
                messages=messages,  # ✅ 传递包含历史上下文的消息列表
                user_id=user_id, 
                session_id=agent.current_session_id
            ):
                if response and response[-1]:
                    assistant_message = response[-1]
                    new_content = assistant_message.content
                    
                    # 检查是否有工具调用
                    if hasattr(assistant_message, 'function_call') and assistant_message.function_call:
                        has_tool_call = True
                        func_call = assistant_message.function_call
                        
                        # 获取工具名称
                        tool_name = 'unknown'
                        if isinstance(func_call, dict):
                            tool_name = func_call.get('name', 'unknown')
                        elif hasattr(func_call, 'name'):
                            tool_name = func_call.name
                        
                        # 工具调用去重
                        if tool_name in tool_call_history:
                            continue
                        tool_call_history.add(tool_name)
                        
                        # 💡 如果有未显示的内容，作为思考过程显示（小字）
                        if response_content and response_content != displayed_content:
                            # 判断是追加还是新内容
                            if displayed_content and response_content.startswith(displayed_content):
                                # 追加模式：显示增量
                                thinking_text = response_content[len(displayed_content):]
                            else:
                                # 新内容或首次显示：显示完整内容
                                thinking_text = response_content
                            
                            if thinking_text.strip():
                                logger.info(f"💭 显示思考过程: {thinking_text[:50]}...")
                                await websocket.send_text(json.dumps({
                                    "type": "thinking",
                                    "subtype": "intermediate",
                                    "content": thinking_text,
                                    "timestamp": datetime.now().isoformat(),
                                    "message_id": f"thinking_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
                                }))
                                displayed_content = response_content
                        
                        # 🔧 立即显示工具调用提示（小字）
                        logger.info(f"🔧 工具调用: {tool_name}")
                        await websocket.send_text(json.dumps({
                            "type": "thinking",
                            "subtype": "tool_call",
                            "content": f"🔧 正在调用工具 {tool_name} 进行处理...",
                            "tool_name": tool_name,
                            "timestamp": datetime.now().isoformat(),
                            "message_id": f"tool_{tool_name}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
                        }))
                        
                        continue
                    
                    # 过滤JSON和指令文本
                    if new_content.strip():
                        is_filtered = False
                        
                        # 检测AI指令文本
                        if '【AI执行指令】' in new_content or '【用户显示内容】' in new_content:
                            is_filtered = True
                            logger.debug(f"🔍 过滤AI指令文本")
                        
                        # 检测JSON
                        elif new_content.strip().startswith(('{', '[')):
                            try:
                                parsed = json.loads(new_content.strip())
                                if isinstance(parsed, (dict, list)):
                                    is_filtered = True
                                    logger.debug(f"🔍 过滤工具JSON结果")
                            except:
                                pass
                        
                        if is_filtered:
                            continue
                    
                    # 累积内容
                    response_content = new_content
            
            # 循环结束，显示最终答案
            if has_tool_call:
                # 有工具调用：显示最终答案（正常字体）
                # 判断是追加还是新内容
                if displayed_content and response_content.startswith(displayed_content):
                    # 追加模式：显示增量（去掉已显示的思考部分）
                    final_content = response_content[len(displayed_content):]
                else:
                    # 新内容或没有已显示内容：显示完整内容
                    final_content = response_content
                
                if final_content.strip():
                    logger.info(f"✅ 显示最终答案: {final_content[:100]}...")
                    
                    await websocket.send_text(json.dumps({
                        "type": "final_answer_start",
                        "message_id": message_id,
                        "timestamp": datetime.now().isoformat()
                    }))
                    
                    await websocket.send_text(json.dumps({
                        "type": "message_chunk",
                        "content": final_content,
                        "full_content": final_content,
                        "timestamp": datetime.now().isoformat(),
                        "message_id": message_id
                    }))
            else:
                # 没有工具调用：直接显示回答（正常字体）
                logger.info(f"✅ 纯文本回答，显示最终结果")
                if response_content:
                    await websocket.send_text(json.dumps({
                        "type": "message_chunk",
                        "content": response_content,
                        "full_content": response_content,
                        "timestamp": datetime.now().isoformat(),
                        "message_id": message_id
                    }))
            
            # 保存assistant的回复到会话
            if response_content:
                self.conversation_manager.add_message(
                    conversation_id=conversation_id,
                    role='assistant',
                    content=response_content
                )
                
                # 检查是否需要生成标题（在保存assistant消息后检查）
                conversation = self.conversation_manager.get_conversation(conversation_id)
                
                if conversation and conversation.title == "新对话":
                    # 检查是否只有用户和助手各一条消息
                    user_messages = [msg for msg in conversation.messages if msg.role == 'user']
                    assistant_messages = [msg for msg in conversation.messages if msg.role == 'assistant']
                    
                    if len(user_messages) == 1 and len(assistant_messages) == 1:
                        try:
                            logger.info(f"🎯 开始为会话 {conversation_id} 生成标题，用户消息: {content[:50]}...")
                            
                            # 异步生成标题，不阻塞消息发送
                            title = await self._generate_title_with_llm(content)
                            self.conversation_manager.update_conversation_title(conversation_id, title)
                            
                            logger.info(f"✅ 标题生成成功: {title}")
                            
                            # 通知前端标题已更新
                            await websocket.send_text(json.dumps({
                                "type": "title_updated",
                                "conversation_id": conversation_id,
                                "title": title,
                                "timestamp": datetime.now().isoformat()
                            }))
                        except Exception as e:
                            logger.error(f"❌ 自动生成标题失败: {e}")
                            # 如果AI生成失败，使用简化标题生成
                            fallback_title = self._generate_simple_title(content)
                            self.conversation_manager.update_conversation_title(conversation_id, fallback_title)
                            
                            # 通知前端使用备用标题
                            await websocket.send_text(json.dumps({
                                "type": "title_updated",
                                "conversation_id": conversation_id,
                                "title": fallback_title,
                                "timestamp": datetime.now().isoformat()
                            }))
            
            # 发送完成状态
            await websocket.send_text(json.dumps({
                "type": "status",
                "content": "完成",
                "timestamp": datetime.now().isoformat(),
                "message_id": message_id
            }))
            
        except Exception as e:
            logger.error(f"❌ 处理聊天消息失败: {e}")
            await websocket.send_text(json.dumps({
                "type": "error",
                "content": f"处理消息时出错：{str(e)}",
                "timestamp": datetime.now().isoformat()
            }))
    
    def _generate_simple_title(self, user_message: str) -> str:
        """
        简化的标题生成（不依赖LLM）
        
        Args:
            user_message: 用户消息
        
        Returns:
            生成的标题
        """
        # 移除常见的开头词汇
        message = user_message.strip()
        
        # 移除问号、感叹号等标点
        message = message.replace('？', '').replace('?', '').replace('！', '').replace('!', '')
        
        # 移除常见的开头
        prefixes_to_remove = [
            '请帮我', '帮我', '请问', '我想', '我需要', '能否', '可以', '能不能',
            '请', '帮我写', '帮我做', '帮我找', '帮我查', '帮我分析'
        ]
        
        for prefix in prefixes_to_remove:
            if message.startswith(prefix):
                message = message[len(prefix):].strip()
                break
        
        # 限制长度
        if len(message) > 20:
            message = message[:20] + '...'
        
        return message if message else '新对话'
    
    async def _generate_title_with_llm(self, first_user_message: str) -> str:
        """
        使用大模型生成会话标题
        
        Args:
            first_user_message: 用户的第一条消息
        
        Returns:
            生成的标题
        """
        try:
            # 检查是否有LLM API配置
            if not settings.DASHSCOPE_API_KEY and not settings.OPENAI_API_KEY:
                logger.warning("⚠️ 未配置LLM API密钥，使用简化标题生成")
                return self._generate_simple_title(first_user_message)
            
            # 导入LLM
            from qwen_agent.llm import get_chat_model
            
            # 创建提示词
            prompt = f"""请根据用户的第一条消息，生成一个简洁的对话标题（不超过20个字）。
            
用户消息：{first_user_message}

要求：
1. 标题要简洁明了，能概括对话主题
2. 不要包含标点符号
3. 不要添加引号或其他修饰
4. 直接输出标题内容，不要有任何前缀或后缀

标题："""
            
            # 调用LLM生成标题
            from ty_mem_agent.config.settings import get_llm_config
            llm_config = get_llm_config()
            llm = get_chat_model(llm_config)
            
            messages = [Message(role=USER, content=prompt)]
            
            # 使用流式调用
            response = None
            for chunk in llm.chat(messages=messages, stream=True):
                response = chunk
            
            # 提取标题
            if response and response[-1]:
                title = response[-1].content.strip()
                
                # 清理标题
                title = title.replace('"', '').replace("'", '').replace('：', '').replace(':', '')
                title = title.replace('标题', '').strip()
                
                # 限制长度
                if len(title) > 30:
                    title = title[:30] + '...'
                
                logger.info(f"✅ LLM生成标题: {title}")
                return title if title else self._generate_simple_title(first_user_message)
            else:
                logger.warning("⚠️ LLM返回空响应，使用简化标题生成")
                return self._generate_simple_title(first_user_message)
                
        except Exception as e:
            logger.error(f"❌ LLM生成标题失败: {e}")
            logger.info("🔄 使用简化标题生成作为备选方案")
            return self._generate_simple_title(first_user_message)
    
    async def _get_or_create_agent(self, user_id: str) -> Optional[TYMemoryAgent]:
        """获取或创建用户的Agent
        
        如果Agent不存在或已过期，自动创建新的Agent
        这样可以确保Agent始终可用，避免"Agent未初始化"的问题
        
        使用锁机制防止并发创建同一个用户的Agent
        
        Args:
            user_id: 用户ID
            
        Returns:
            TYMemoryAgent实例，如果创建失败则返回None
        """
        try:
            # 第一层检查：快速路径，如果Agent存在且未过期，直接返回
            agent = self.user_agents.get(user_id)
            
            if agent:
                # Agent存在，检查是否过期
                last_used = self.agent_last_used.get(user_id)
                if last_used:
                    idle_time = (datetime.now() - last_used).total_seconds()
                    if idle_time > self.agent_idle_timeout:
                        # Agent已过期，需要清理并创建新的
                        logger.info(f"🔄 Agent已过期（空闲{idle_time//60:.1f}分钟），为用户 {user_id} 创建新Agent")
                        await self._cleanup_agent(user_id)
                        agent = None
                    else:
                        # Agent未过期，直接返回
                        logger.debug(f"✅ 使用现有Agent: {user_id}（空闲{idle_time//60:.1f}分钟）")
                        return agent
                else:
                    # 没有记录最后使用时间，更新并返回
                    self.agent_last_used[user_id] = datetime.now()
                    return agent
            
            # 第二层检查：Agent不存在或已过期，需要创建新的
            # 使用锁机制防止并发创建
            if user_id not in self.agent_creation_locks:
                self.agent_creation_locks[user_id] = asyncio.Lock()
            
            async with self.agent_creation_locks[user_id]:
                # 双重检查：在获取锁后再次检查，防止其他线程已经创建了
                agent = self.user_agents.get(user_id)
                if agent:
                    # 其他线程已经创建了，直接返回
                    logger.debug(f"✅ 使用其他线程创建的Agent: {user_id}")
                    self.agent_last_used[user_id] = datetime.now()
                    return agent
                
                # 创建新的Agent
                logger.info(f"🆕 为用户 {user_id} 创建新Agent")
                try:
                    agent = TYMemoryAgent()
                    session = user_manager.get_user_session(user_id)
                    session_id = session.session_id if session else f"ws_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    
                    await agent.set_user_context(user_id, session_id)
                    self.user_agents[user_id] = agent
                    self.agent_last_used[user_id] = datetime.now()
                    
                    logger.info(f"✅ Agent创建成功: {user_id}")
                    return agent
                    
                except Exception as create_error:
                    logger.error(f"❌ 创建Agent实例失败: {create_error}")
                    import traceback
                    logger.error(traceback.format_exc())
                    # 清理可能的部分创建状态
                    if user_id in self.user_agents:
                        del self.user_agents[user_id]
                    if user_id in self.agent_last_used:
                        del self.agent_last_used[user_id]
                    return None
            
        except Exception as e:
            logger.error(f"❌ 获取或创建Agent失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    async def _cleanup_agent(self, user_id: str):
        """清理用户的Agent
        
        注意：清理时使用锁，防止与创建操作冲突
        """
        try:
            # 获取锁，防止在清理时其他线程正在创建
            if user_id not in self.agent_creation_locks:
                self.agent_creation_locks[user_id] = asyncio.Lock()
            
            async with self.agent_creation_locks[user_id]:
                if user_id in self.user_agents:
                    agent = self.user_agents[user_id]
                    try:
                        await agent.cleanup()
                    except Exception as cleanup_error:
                        logger.warning(f"⚠️ Agent清理时出错（继续删除）: {cleanup_error}")
                    finally:
                        del self.user_agents[user_id]
                    logger.info(f"🧹 已清理Agent: {user_id}")
                
                if user_id in self.agent_last_used:
                    del self.agent_last_used[user_id]
                
                # 清理锁（延迟清理，避免频繁创建锁）
                # 注意：不立即删除锁，因为用户可能很快重新连接
                
        except Exception as e:
            logger.error(f"❌ 清理Agent失败: {e}")
    
    async def _cleanup_idle_agents(self):
        """定期清理长时间未使用的Agent
        
        这是一个后台任务，定期检查并清理长时间未使用的Agent
        """
        try:
            current_time = datetime.now()
            expired_users = []
            
            for user_id, last_used in list(self.agent_last_used.items()):
                if user_id in self.active_connections:
                    # 用户还在线，跳过
                    continue
                
                idle_time = (current_time - last_used).total_seconds()
                if idle_time > self.agent_idle_timeout:
                    expired_users.append((user_id, idle_time))
            
            # 清理过期的Agent
            for user_id, idle_time in expired_users:
                logger.info(f"🧹 清理长时间未使用的Agent: {user_id}（空闲{idle_time//60:.1f}分钟）")
                await self._cleanup_agent(user_id)
                
            if expired_users:
                logger.info(f"✅ 清理完成，共清理 {len(expired_users)} 个过期Agent")
                
        except Exception as e:
            logger.error(f"❌ 清理空闲Agent失败: {e}")
    
    async def _get_user_memory_summary(self, user_id: str) -> Dict:
        """获取用户记忆摘要"""
        try:
            agent = await self._get_or_create_agent(user_id)
            if agent:
                return await agent.get_user_summary(user_id)
            else:
                # 直接从集成记忆系统获取
                integrated_memory = get_integrated_memory()
                context = await integrated_memory.get_user_context(user_id, "summary")
                return {
                    "user_profile": context.get("user_profile", {}),
                    "memory_count": len(context.get("relevant_memories", [])),
                    "insights_count": len(context.get("insights", []))
                }
        except Exception as e:
            logger.error(f"❌ 获取用户记忆摘要失败: {e}")
            return {}
    
    async def _disconnect_user(self, user_id: str):
        """断开用户连接
        
        注意：不断开连接时不立即删除Agent，而是保留一段时间
        这样可以避免用户重新连接时Agent未初始化的问题
        """
        try:
            # 移除连接
            if user_id in self.active_connections:
                del self.active_connections[user_id]
            
            # 更新Agent最后使用时间（不断开连接时也更新，用于后续清理）
            if user_id in self.user_agents:
                self.agent_last_used[user_id] = datetime.now()
                logger.info(f"🔌 用户断开连接: {user_id}，Agent保留（将在{self.agent_idle_timeout//60}分钟后自动清理）")
            else:
                logger.info(f"🔌 用户断开连接: {user_id}")
            
            # 不立即删除Agent，而是通过定期清理任务来删除长时间未使用的Agent
            # 这样可以支持用户快速重连，避免Agent未初始化的问题
            
        except Exception as e:
            logger.error(f"❌ 断开用户连接失败: {e}")
    
    
    def _register_todo_routes(self):
        """注册待办管理路由"""
        from ty_mem_agent.server.todo_api import router as todo_router
        self.app.include_router(todo_router)
        
        # 添加待办管理页面路由
        @self.app.get("/todos")
        async def todos_page():
            """待办管理页面"""
            template_path = Path(__file__).parent / "templates" / "todos.html"
            if template_path.exists():
                return FileResponse(template_path)
            else:
                return HTMLResponse(content="<h1>待办管理页面未找到</h1>", status_code=404)
        
        logger.info("✅ 待办管理路由已注册")
    
    async def start_server(self):
        """启动服务器"""
        import uvicorn
        
        # 启动定期清理任务
        asyncio.create_task(self._periodic_cleanup_task())
        
        logger.info(f"🚀 启动Chat Server: {settings.HOST}:{settings.PORT}")
        
        config = uvicorn.Config(
            self.app,
            host=settings.HOST,
            port=settings.PORT,
            log_level=settings.LOG_LEVEL.lower(),
            reload=settings.DEBUG
        )
        
        server = uvicorn.Server(config)
        await server.serve()
    
    async def _periodic_cleanup_task(self):
        """定期清理任务
        
        每5分钟检查一次，清理长时间未使用的Agent
        """
        while True:
            try:
                await asyncio.sleep(5 * 60)  # 每5分钟执行一次
                await self._cleanup_idle_agents()
            except asyncio.CancelledError:
                logger.info("🛑 定期清理任务已取消")
                break
            except Exception as e:
                logger.error(f"❌ 定期清理任务出错: {e}")
    
    async def cleanup(self):
        """清理资源"""
        try:
            # 断开所有连接
            for user_id in list(self.active_connections.keys()):
                await self._disconnect_user(user_id)
            
            # 清理所有Agent
            for user_id in list(self.user_agents.keys()):
                await self._cleanup_agent(user_id)
            
            logger.info("🧹 Chat Server 资源清理完成")
            
        except Exception as e:
            logger.error(f"❌ Chat Server 清理失败: {e}")


if __name__ == "__main__":
    # 测试聊天服务器
    async def test_server():
        server = ChatServer()
        try:
            await server.start_server()
        finally:
            await server.cleanup()
    
    asyncio.run(test_server())
