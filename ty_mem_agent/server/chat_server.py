#!/usr/bin/env python3
"""
聊天服务器
基于FastAPI的多用户聊天服务，集成TY Memory Agent
"""

import asyncio
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from loguru import logger

# 使用简洁的绝对导入
from ty_mem_agent.config.settings import settings
from ty_mem_agent.agents.ty_memory_agent import TYMemoryAgent
from ty_mem_agent.memory.user_memory import integrated_memory
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
            return HTMLResponse(self._get_demo_html())
    
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
            await websocket.send_text(json.dumps({
                "type": "status",
                "content": "正在思考...",
                "timestamp": datetime.now().isoformat()
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
            
            async for response in agent._run([user_message], user_id=user_id, session_id=agent.current_session_id):
                if response and response[-1]:
                    assistant_message = response[-1]
                    new_content = assistant_message.content
                    
                    # 发送增量内容
                    if new_content != response_content:
                        response_content = new_content
                        
                        await websocket.send_text(json.dumps({
                            "type": "message",
                            "content": response_content,
                            "timestamp": datetime.now().isoformat(),
                            "message_id": message_id,
                            "metadata": {
                                "type": "assistant_response",
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
    
    def _get_demo_html(self) -> str:
        """获取演示页面HTML"""
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

        function displayMessage(data) {
            const chatContainer = document.getElementById('chatContainer');
            const messageDiv = document.createElement('div');
            messageDiv.className = 'message ' + (data.type === 'message' ? 'assistant-message' : 'status');
            
            if (data.type === 'error') {
                messageDiv.className = 'message error';
            }
            
            messageDiv.innerHTML = `
                <div>${data.content}</div>
                <small>${new Date(data.timestamp).toLocaleTimeString()}</small>
            `;
            
            chatContainer.appendChild(messageDiv);
            chatContainer.scrollTop = chatContainer.scrollHeight;
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
