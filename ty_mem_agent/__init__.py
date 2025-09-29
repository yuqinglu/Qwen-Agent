#!/usr/bin/env python3
"""
TY Memory Agent - 智能记忆助手系统

集成MemOS记忆系统、QwenAgent框架和MCP工具调用的多用户智能对话系统

主要特性:
- 🧠 智能记忆系统 (MemOS + 本地存储)
- 🤖 智能Agent (基于QwenAgent)  
- 🔧 MCP工具集成 (滴滴叫车、高德天气等)
- 👥 多用户支持 (认证、会话管理)
- 💬 实时聊天 (WebSocket + REST API)
"""

__version__ = "1.0.0"
__author__ = "TY Memory Agent Team"
__description__ = "智能记忆助手系统"

# 统一导入策略 - 使用绝对导入
from .agents.ty_memory_agent import TYMemoryAgent
from .server.chat_server import ChatServer
from .server.user_manager import UserManager
from .config.settings import settings
from .memory.memos_client import memory_manager
from .memory.user_memory import integrated_memory
from .mcp.enhanced_mcp_router import get_enhanced_router
from .utils.logger_config import setup_logger, get_logger

__all__ = [
    'TYMemoryAgent',
    'ChatServer', 
    'UserManager',
    'settings',
    'memory_manager',
    'integrated_memory',
    'get_enhanced_router',
    'setup_logger',
    'get_logger'
]