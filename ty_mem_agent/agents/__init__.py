#!/usr/bin/env python3
"""
TY Memory Agent 代理模块

包含多个专用Agent：
- TYMemoryAgent: 通用记忆智能助理
- TodoChatAgent: 待办聊天专用Agent
- PhoneAgent: 手机操作Agent（基于Open-AutoGLM）
- MultiAgentRouter: 多Agent路由器
"""

from .ty_memory_agent import TYMemoryAgent
from .todo_chat_agent import TodoChatAgent, get_todo_chat_agent
from .phone_agent import PhoneAgent, get_phone_agent
from .multi_agent_router import (
    MultiAgentRouter, 
    get_multi_agent_router,
    AgentType,
    RoutingResult
)

__all__ = [
    # 核心Agent
    'TYMemoryAgent',
    'TodoChatAgent',
    'PhoneAgent',
    
    # 路由器
    'MultiAgentRouter',
    'AgentType',
    'RoutingResult',
    
    # 工厂函数
    'get_todo_chat_agent',
    'get_phone_agent',
    'get_multi_agent_router',
]
