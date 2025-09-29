#!/usr/bin/env python3
"""
TY Memory Agent - 基于QwenAgent的智能记忆代理
直接集成QwenAgent内置工具，简洁高效
"""

import sys
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from loguru import logger

# 添加QwenAgent路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    from qwen_agent.agents.assistant import Assistant
    from qwen_agent.llm import get_chat_model
    from qwen_agent.tools.amap_weather import AmapWeather
    from qwen_agent.tools.base import BaseTool
    logger.info("✅ 成功导入QwenAgent核心组件")
except ImportError as e:
    logger.error(f"❌ 无法导入QwenAgent核心组件: {e}")
    raise

# 本地导入
from ty_mem_agent.config.settings import settings, get_llm_config
from ty_mem_agent.memory.memos_client import memory_manager
from ty_mem_agent.memory.user_memory import integrated_memory
from ty_mem_agent.mcp.qwen_style_didi_service import QwenStyleDidiService


class TYMemoryAgent(Assistant):
    """TY记忆智能代理 - 基于QwenAgent Assistant
    
    特性：
    - 继承QwenAgent的Assistant能力
    - 集成QwenAgent内置工具
    - 支持记忆系统
    - 支持多用户
    """
    
    def __init__(self, 
                 function_list: Optional[List[Union[str, Dict, BaseTool]]] = None,
                 llm: Optional[Union[Dict, Any]] = None,
                 system_message: Optional[str] = None,
                 name: Optional[str] = "TY Memory Agent",
                 description: Optional[str] = None,
                 **kwargs):
        
        # 默认系统消息
        if not system_message:
            system_message = self._build_system_message()
        
        if not description:
            description = ("智能记忆助手，具备长期记忆能力、多用户支持、"
                          "智能工具调用等功能，可以叫车、查天气等")
        
        # 默认LLM配置
        if llm is None:
            llm_config = get_llm_config()
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
        
        # 初始化记忆系统
        self.memory_manager = memory_manager
        self.integrated_memory = integrated_memory
        
        logger.info(f"✅ 成功创建TY记忆智能代理: {self.name}")
        logger.info(f"✅ 可用工具: {list(self.function_map.keys())}")
    
    def _build_system_message(self) -> str:
        """构建系统消息"""
        return """你是一个智能记忆助手，具备以下能力：

🧠 记忆能力：
- 长期记忆：记住用户的基本信息、偏好、历史对话
- 上下文记忆：理解当前对话的上下文
- 多用户支持：为不同用户提供个性化服务

🛠️ 工具能力：
- 天气查询：使用amap_weather工具查询天气
- 叫车服务：使用didi_ride工具预约车辆
- 智能分析：基于用户记忆提供个性化建议

💡 交互原则：
- 主动利用用户记忆提供个性化服务
- 根据用户历史偏好调整回复风格
- 在适当时机调用工具满足用户需求
- 保持友好、专业的对话风格

请根据用户的需求和记忆信息，提供最合适的帮助。"""
    
    def _get_default_tools(self) -> List[Union[str, Dict, BaseTool]]:
        """获取默认工具列表"""
        tools = []
        
        # 添加QwenAgent内置天气工具
        try:
            weather_tool = AmapWeather()
            tools.append(weather_tool)
            logger.info("✅ 添加QwenAgent内置天气工具")
        except Exception as e:
            logger.warning(f"⚠️ 无法添加天气工具: {e}")
        
        # 添加自定义滴滴叫车工具
        try:
            didi_tool = QwenStyleDidiService()
            tools.append(didi_tool)
            logger.info("✅ 添加滴滴叫车工具")
        except Exception as e:
            logger.warning(f"⚠️ 无法添加滴滴工具: {e}")
        
        return tools
    
    def run_with_memory(self, 
                       messages: List[Any], 
                       user_id: str = "default_user",
                       session_id: str = "default_session",
                       **kwargs) -> List[Any]:
        """带记忆的对话运行"""
        try:
            # 获取用户记忆
            user_memory = self._get_user_memory(user_id, session_id)
            
            # 构建带记忆的消息
            enhanced_messages = self._enhance_messages_with_memory(messages, user_memory)
            
            # 运行对话
            response = []
            for chunk in self.run(messages=enhanced_messages, **kwargs):
                response = chunk
                yield chunk
            
            # 更新用户记忆
            self._update_user_memory(user_id, session_id, messages, response)
            
        except Exception as e:
            logger.error(f"❌ 带记忆对话运行失败: {e}")
            # 回退到普通对话
            for chunk in self.run(messages=messages, **kwargs):
                yield chunk
    
    def _get_user_memory(self, user_id: str, session_id: str) -> Dict[str, Any]:
        """获取用户记忆"""
        try:
            # 获取用户基本信息
            user_profile = self.integrated_memory.get_user_profile(user_id)
            
            # 获取对话历史
            conversation_history = self.integrated_memory.get_conversation_history(
                user_id, session_id, limit=5
            )
            
            return {
                "user_profile": user_profile,
                "conversation_history": conversation_history,
                "session_id": session_id
            }
        except Exception as e:
            logger.warning(f"⚠️ 获取用户记忆失败: {e}")
            return {}
    
    def _enhance_messages_with_memory(self, messages: List[Any], user_memory: Dict[str, Any]) -> List[Any]:
        """用记忆增强消息"""
        try:
            enhanced_messages = messages.copy()
            
            # 添加用户记忆信息到第一条消息
            if enhanced_messages and user_memory:
                memory_context = self._format_memory_context(user_memory)
                if memory_context:
                    # 在第一条消息前添加记忆上下文
                    enhanced_messages.insert(0, {
                        "role": "system",
                        "content": f"用户记忆信息：\n{memory_context}"
                    })
            
            return enhanced_messages
        except Exception as e:
            logger.warning(f"⚠️ 记忆增强失败: {e}")
            return messages
    
    def _format_memory_context(self, user_memory: Dict[str, Any]) -> str:
        """格式化记忆上下文"""
        try:
            context_parts = []
            
            # 用户基本信息
            user_profile = user_memory.get("user_profile", {})
            if user_profile:
                context_parts.append(f"用户信息: {user_profile}")
            
            # 对话历史
            conversation_history = user_memory.get("conversation_history", [])
            if conversation_history:
                context_parts.append(f"最近对话: {conversation_history}")
            
            return "\n".join(context_parts) if context_parts else ""
        except Exception as e:
            logger.warning(f"⚠️ 格式化记忆上下文失败: {e}")
            return ""
    
    def _update_user_memory(self, 
                           user_id: str, 
                           session_id: str, 
                           messages: List[Any], 
                           response: List[Any]):
        """更新用户记忆"""
        try:
            # 保存对话到记忆系统
            self.integrated_memory.save_conversation(
                user_id, session_id, messages, response
            )
            
            # 分析并更新用户偏好
            self._analyze_user_preferences(user_id, messages, response)
            
        except Exception as e:
            logger.warning(f"⚠️ 更新用户记忆失败: {e}")
    
    def _analyze_user_preferences(self, 
                                 user_id: str, 
                                 messages: List[Any], 
                                 response: List[Any]):
        """分析用户偏好"""
        try:
            # 简单的偏好分析逻辑
            # 实际应用中可以使用更复杂的NLP分析
            
            # 检查是否使用了工具
            tool_usage = []
            for msg in response:
                if hasattr(msg, 'function_call') and msg.function_call:
                    tool_usage.append(msg.function_call.name)
            
            if tool_usage:
                # 更新用户工具使用偏好
                self.integrated_memory.update_user_preferences(
                    user_id, {"preferred_tools": tool_usage}
                )
                
        except Exception as e:
            logger.warning(f"⚠️ 分析用户偏好失败: {e}")


if __name__ == "__main__":
    # 测试TY记忆智能代理
    from ty_mem_agent.utils.logger_config import get_logger
    test_logger = get_logger("TYMemoryAgentTest")
    
    def test_ty_memory_agent():
        test_logger.info("🧪 测试TY记忆智能代理...")
        
        try:
            # 创建代理实例
            agent = TYMemoryAgent()
            test_logger.info(f"✅ 代理创建成功: {agent.name}")
            test_logger.info(f"✅ 代理描述: {agent.description}")
            test_logger.info(f"✅ 可用工具: {list(agent.function_map.keys())}")
            
            # 测试带记忆的对话
            test_messages = [
                {"role": "user", "content": "你好，我是张三，我想了解一下今天的天气"}
            ]
            
            test_logger.info("🎯 测试带记忆的对话...")
            for response in agent.run_with_memory(
                messages=test_messages,
                user_id="zhang_san",
                session_id="test_session"
            ):
                test_logger.info(f"📝 响应: {response}")
            
            test_logger.info("🎉 TY记忆智能代理测试完成！")
            
        except Exception as e:
            test_logger.error(f"❌ 测试失败: {e}")
            import traceback
            traceback.print_exc()
    
    test_ty_memory_agent()
