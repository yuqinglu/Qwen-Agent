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
        
        # 初始化路由
        self._setup_routes()
        
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
                return HTMLResponse(self._get_fallback_html())
    
    async def _handle_websocket_connection(self, websocket: WebSocket, user):
        """处理WebSocket连接"""
        await websocket.accept()
        
        user_id = user.user_id
        self.active_connections[user_id] = websocket
        
        # 创建或获取用户的Agent
        if user_id not in self.user_agents:
            agent = TYMemoryAgent()
            session = user_manager.get_user_session(user_id)
            session_id = session.session_id if session else f"ws_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            await agent.set_user_context(user_id, session_id)
            self.user_agents[user_id] = agent
        
        logger.info(f"🔗 用户连接: {user.username} ({user_id})")
        
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
            welcome_parts.append("• 🚗 叫车服务（滴滴）")
            welcome_parts.append("• 🌤️ 查询天气（高德）")
            welcome_parts.append("• 🕐 时间查询")
            welcome_parts.append("• 🎨 图像生成")
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
            
            # 发送正在处理消息
            thinking_message_id = f"thinking_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            await websocket.send_text(json.dumps({
                "type": "status",
                "content": "正在思考...",
                "timestamp": datetime.now().isoformat(),
                "message_id": thinking_message_id
            }))
            
            # 获取用户的Agent
            agent = self.user_agents.get(user_id)
            if not agent:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "content": "Agent未初始化，请重新连接",
                    "timestamp": datetime.now().isoformat()
                }))
                return
            
            # 创建消息对象
            user_message = Message(role=USER, content=content)
            
            # 处理消息并流式返回
            response_content = ""
            message_id = f"msg_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            first_response = True  # 标记是否是第一次响应
            has_tool_call = False  # 标记是否有工具调用
            
            # 使用run_with_memory进行带记忆的对话
            async for response in agent.run_with_memory(
                messages=[user_message], 
                user_id=user_id, 
                session_id=agent.current_session_id
            ):
                if response and response[-1]:
                    assistant_message = response[-1]
                    new_content = assistant_message.content
                    
                    # 检查是否有工具调用（这通常表示中间步骤）
                    if hasattr(assistant_message, 'function_call') and assistant_message.function_call:
                        has_tool_call = True
                        func_call = assistant_message.function_call
                        
                        # 完整打印工具调用信息
                        logger.info("=" * 80)
                        logger.info(f"🔧 工具调用检测")
                        logger.info("-" * 80)
                        
                        # 打印完整的 function_call 对象
                        logger.info(f"function_call 类型: {type(func_call)}")
                        logger.info(f"function_call 完整内容: {func_call}")
                        
                        # 尝试不同的方式获取工具名称和参数
                        tool_name = 'unknown'
                        tool_args = 'N/A'
                        
                        if isinstance(func_call, dict):
                            tool_name = func_call.get('name', 'unknown')
                            tool_args = func_call.get('arguments', 'N/A')
                        elif hasattr(func_call, 'name'):
                            tool_name = func_call.name
                            tool_args = getattr(func_call, 'arguments', 'N/A')
                        
                        logger.info(f"工具名称: {tool_name}")
                        
                        # 完整显示参数（不截断）
                        if tool_args and tool_args != 'N/A':
                            args_str = str(tool_args)
                            logger.info(f"调用参数 (长度 {len(args_str)}): {args_str}")
                        else:
                            logger.warning(f"⚠️ 调用参数为空或 N/A: {tool_args}")
                        
                        logger.info("-" * 80)
                        
                        # 注意：有 function_call 的 Message，其 content 通常为空
                        # 这是正常的，因为这是工具调用请求，不是工具返回
                        # 工具的实际返回值会在下一条 Message 中
                        if new_content:
                            content_str = str(new_content)
                            logger.info(f"Message content (长度 {len(content_str)}): {content_str[:200]}...")
                        else:
                            logger.debug("Message content 为空（这是正常的，工具调用请求阶段）")
                        logger.info("=" * 80)
                        
                        continue  # 跳过工具调用的中间结果，只显示最终回答
                    
                    # 如果是第一次响应，先隐藏"正在思考..."消息
                    if first_response and new_content.strip():
                        # 发送隐藏"正在思考..."的消息
                        await websocket.send_text(json.dumps({
                            "type": "hide_thinking",
                            "message_id": thinking_message_id,
                            "timestamp": datetime.now().isoformat()
                        }))
                        first_response = False
                    
                    # 发送增量内容
                    if new_content != response_content:
                        # 计算增量内容
                        if new_content.startswith(response_content):
                            # 新内容是旧内容的扩展，发送增量部分
                            incremental_content = new_content[len(response_content):]
                            response_content = new_content
                            
                            await websocket.send_text(json.dumps({
                                "type": "message_chunk",
                                "content": incremental_content,
                                "full_content": response_content,
                                "timestamp": datetime.now().isoformat(),
                                "message_id": message_id,
                                "metadata": {
                                    "type": "assistant_response_chunk",
                                    "extra": getattr(assistant_message, 'extra', {})
                                }
                            }))
                        else:
                            # 内容完全不同（可能是工具调用后重新生成）
                            # 如果有工具调用，这可能是最终回答，替换之前的内容
                            logger.debug(f"🔄 内容变化: '{response_content[:50]}...' -> '{new_content[:50]}...'")
                            response_content = new_content
                            
                            await websocket.send_text(json.dumps({
                                "type": "message_chunk",
                                "content": new_content,  # 发送完整内容作为增量
                                "full_content": new_content,
                                "timestamp": datetime.now().isoformat(),
                                "message_id": message_id,
                                "metadata": {
                                    "type": "assistant_response_chunk",
                                    "replace": True,  # 标记这是替换而不是追加
                                    "extra": getattr(assistant_message, 'extra', {})
                                }
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
    
    async def _get_user_memory_summary(self, user_id: str) -> Dict:
        """获取用户记忆摘要"""
        try:
            agent = self.user_agents.get(user_id)
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
        """断开用户连接"""
        try:
            # 移除连接
            if user_id in self.active_connections:
                del self.active_connections[user_id]
            
            # 清理Agent
            if user_id in self.user_agents:
                agent = self.user_agents[user_id]
                await agent.cleanup()
                del self.user_agents[user_id]
            
            logger.info(f"🔌 用户断开: {user_id}")
            
        except Exception as e:
            logger.error(f"❌ 断开用户连接失败: {e}")
    
    def _get_fallback_html(self) -> str:
        """获取备用演示页面HTML（当外部文件不存在时使用）"""
        return """
<!DOCTYPE html>
<html>
<head>
    <title>TY Memory Agent Chat Demo</title>
    <meta charset="UTF-8">
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }
        .container { max-width: 800px; margin: 0 auto; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .header { background: #007bff; color: white; padding: 20px; text-align: center; }
        .login-form { padding: 20px; border-bottom: 1px solid #eee; }
        .chat-container { height: 400px; overflow-y: auto; padding: 20px; border-bottom: 1px solid #eee; }
        .message { margin-bottom: 15px; padding: 10px; border-radius: 5px; }
        .user-message { background: #e3f2fd; margin-left: 50px; }
        .assistant-message { background: #f3e5f5; margin-right: 50px; }
        .input-container { padding: 20px; display: flex; gap: 10px; }
        input, button { padding: 10px; border: 1px solid #ddd; border-radius: 5px; }
        input[type="text"] { flex: 1; }
        button { background: #007bff; color: white; border: none; cursor: pointer; }
        button:hover { background: #0056b3; }
        .status { color: #666; font-style: italic; }
        .error { color: #dc3545; }
        .message-content { word-wrap: break-word; white-space: pre-wrap; }
        .message-time { color: #999; font-size: 0.8em; }
        .assistant-message { border-left: 3px solid #007bff; }
        .user-message { border-left: 3px solid #28a745; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 TY Memory Agent</h1>
            <p>智能记忆助手演示</p>
        </div>
        
        <div class="login-form" id="loginForm">
            <h3>请先登录</h3>
            <input type="text" id="username" placeholder="用户名 (test)" value="test">
            <input type="password" id="password" placeholder="密码 (test123)" value="test123">
            <button onclick="login()">登录</button>
            <p class="status">默认用户: test/test123 或 admin/admin123</p>
        </div>
        
        <div class="chat-container" id="chatContainer" style="display: none;"></div>
        
        <div class="input-container" id="inputContainer" style="display: none;">
            <input type="text" id="messageInput" placeholder="输入消息..." onkeypress="handleKeyPress(event)">
            <button onclick="sendMessage()">发送</button>
            <button onclick="logout()">登出</button>
        </div>
    </div>

    <script>
        let ws = null;
        let token = null;

        async function login() {
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            
            try {
                const response = await fetch('/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });
                
                if (response.ok) {
                    const data = await response.json();
                    token = data.access_token;
                    connectWebSocket();
                    
                    document.getElementById('loginForm').style.display = 'none';
                    document.getElementById('chatContainer').style.display = 'block';
                    document.getElementById('inputContainer').style.display = 'flex';
                } else {
                    alert('登录失败');
                }
            } catch (error) {
                alert('登录错误: ' + error.message);
            }
        }

        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws/${token}`);
            
            ws.onmessage = function(event) {
                const data = JSON.parse(event.data);
                displayMessage(data);
            };
            
            ws.onclose = function() {
                console.log('WebSocket连接关闭');
            };
        }

        // 存储当前正在流式输出的消息
        let currentStreamingMessage = null;
        
        function displayMessage(data) {
            const chatContainer = document.getElementById('chatContainer');
            
            if (data.type === 'hide_thinking') {
                // 隐藏"正在思考..."消息
                const thinkingElement = document.getElementById('status-' + data.message_id);
                if (thinkingElement) {
                    thinkingElement.style.display = 'none';
                }
                
            } else if (data.type === 'message_chunk') {
                // 处理流式消息块
                if (!currentStreamingMessage) {
                    // 创建新的流式消息容器
                    currentStreamingMessage = document.createElement('div');
                    currentStreamingMessage.className = 'message assistant-message';
                    currentStreamingMessage.id = 'streaming-' + data.message_id;
                    currentStreamingMessage.innerHTML = `
                        <div class="message-content"></div>
                        <small class="message-time">${new Date(data.timestamp).toLocaleTimeString()}</small>
                    `;
                    chatContainer.appendChild(currentStreamingMessage);
                }
                
                // 追加增量内容
                const contentDiv = currentStreamingMessage.querySelector('.message-content');
                contentDiv.textContent = data.full_content;
                
                // 滚动到底部
                chatContainer.scrollTop = chatContainer.scrollHeight;
                
            } else if (data.type === 'message') {
                // 处理完整消息
                if (currentStreamingMessage) {
                    // 完成当前流式消息
                    currentStreamingMessage = null;
                }
                
                const messageDiv = document.createElement('div');
                messageDiv.className = 'message assistant-message';
                messageDiv.innerHTML = `
                    <div class="message-content">${data.content}</div>
                    <small class="message-time">${new Date(data.timestamp).toLocaleTimeString()}</small>
                `;
                
                chatContainer.appendChild(messageDiv);
                chatContainer.scrollTop = chatContainer.scrollHeight;
                
            } else if (data.type === 'status') {
                // 处理状态消息
                if (data.content === '完成' && currentStreamingMessage) {
                    // 流式消息完成，清理引用
                    currentStreamingMessage = null;
                } else {
                    // 显示状态消息
                    const messageDiv = document.createElement('div');
                    messageDiv.className = 'message status';
                    messageDiv.id = 'status-' + (data.message_id || 'default');
                    messageDiv.innerHTML = `
                        <div class="message-content">${data.content}</div>
                        <small class="message-time">${new Date(data.timestamp).toLocaleTimeString()}</small>
                    `;
                    
                    chatContainer.appendChild(messageDiv);
                    chatContainer.scrollTop = chatContainer.scrollHeight;
                }
                
            } else if (data.type === 'error') {
                // 处理错误消息
                const messageDiv = document.createElement('div');
                messageDiv.className = 'message error';
                messageDiv.innerHTML = `
                    <div class="message-content">${data.content}</div>
                    <small class="message-time">${new Date(data.timestamp).toLocaleTimeString()}</small>
                `;
                
                chatContainer.appendChild(messageDiv);
                chatContainer.scrollTop = chatContainer.scrollHeight;
            }
        }

        function sendMessage() {
            const input = document.getElementById('messageInput');
            const message = input.value.trim();
            
            if (message && ws) {
                // 显示用户消息
                const chatContainer = document.getElementById('chatContainer');
                const messageDiv = document.createElement('div');
                messageDiv.className = 'message user-message';
                messageDiv.innerHTML = `
                    <div>${message}</div>
                    <small>${new Date().toLocaleTimeString()}</small>
                `;
                chatContainer.appendChild(messageDiv);
                
                // 发送消息
                ws.send(JSON.stringify({ content: message }));
                input.value = '';
                chatContainer.scrollTop = chatContainer.scrollHeight;
            }
        }

        function handleKeyPress(event) {
            if (event.key === 'Enter') {
                sendMessage();
            }
        }

        async function logout() {
            if (ws) {
                ws.close();
            }
            
            if (token) {
                await fetch('/auth/logout', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}` }
                });
            }
            
            token = null;
            document.getElementById('loginForm').style.display = 'block';
            document.getElementById('chatContainer').style.display = 'none';
            document.getElementById('inputContainer').style.display = 'none';
            document.getElementById('chatContainer').innerHTML = '';
        }
    </script>
</body>
</html>
        """
    
    async def start_server(self):
        """启动服务器"""
        import uvicorn
        
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
    
    async def cleanup(self):
        """清理资源"""
        try:
            # 断开所有连接
            for user_id in list(self.active_connections.keys()):
                await self._disconnect_user(user_id)
            
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
