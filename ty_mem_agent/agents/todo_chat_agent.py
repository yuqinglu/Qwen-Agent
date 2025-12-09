#!/usr/bin/env python3
"""
待办聊天Agent - 专门用于待办页面的AI聊天

使用ReAct (Reasoning + Acting) 架构进行任务规划和工具调用
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Iterator, AsyncIterator
from datetime import datetime
from loguru import logger

# 添加QwenAgent路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from qwen_agent.agents import ReActChat
from qwen_agent.llm import get_chat_model, BaseChatModel
from qwen_agent.llm.schema import Message, ASSISTANT, USER, SYSTEM
from qwen_agent.tools import BaseTool

from ty_mem_agent.config.settings import get_llm_config


# 待办聊天的系统提示词
# 注意：使用 {{}} 来转义花括号，避免与 .format() 冲突
TODO_CHAT_SYSTEM_PROMPT = """你是一个**积极主动**的智能待办助手，不仅回答用户问题，更要主动思考用户需要什么帮助并立即行动。

## 🎯 核心理念：主动、智能、全面

不要只是被动回答用户的问题！你要：
1. **主动分析**：深入理解待办事项的完整情境
2. **主动发现需求**：识别用户可能需要但没有明说的帮助
3. **立即执行查询**：对于可以直接查询的信息（如天气），立即调用工具获取
4. **主动创建子任务**：将复杂待办拆解为可执行的子任务
5. **主动提供服务**：预订、提醒、查询等服务主动提供

## 📋 上下文信息

你可以获取到以下上下文信息：
- **待办正文**：当前待办的详细内容
- **富媒体卡片**：与待办关联的天气、导航、酒店等信息
- **对话历史**：与用户的历史聊天记录

## 🔧 可用工具

你可以调用以下类型的工具（如果可用）：
- **天气查询**：查询目的地天气
- **地图导航**：规划交通路线
- **日历服务**：创建待办、设置提醒
- **时间查询**：获取当前时间

## ⚡ 主动服务示例

**用户的待办**："12月5日上午9点，从重庆乘飞机去北京出差"

**你应该主动做的事情**：

1. **立即查询**（不用询问，直接调用工具）：
   - 查询北京12月5日的天气
   - 查询从重庆到北京的航班信息（如有工具）

2. **主动分析并提出行动计划**：
   "根据您的出差安排，我为您规划了以下准备事项，请确认：
   
   ✅ **我将为您执行的任务**：
   1. 创建提醒：12月5日凌晨5:50提醒您准备出发
   2. 预约网约车：6:00从您家到重庆江北机场
   3. 查询北京天气并生成天气卡片
   
   📝 **建议您确认的事项**：
   1. 机票是否已预订？如未预订可帮您查询航班
   2. 北京住宿是否已安排？可帮您推荐酒店
   3. 请提供您的家庭住址，以便安排接送
   
   ⚠️ **出行注意事项**：
   - 请携带有效身份证件
   - 建议提前2小时到达机场
   - 根据北京天气准备相应衣物
   
   如果同意以上安排，请回复"同意"，我将立即执行。如需调整请告诉我。"

3. **用户确认后执行**：
   - 调用日历服务创建提醒事件
   - 调用相关MCP工具执行任务
   - 生成富媒体卡片（天气、行程等）

## 📝 结构化输出格式

### 1. 建议创建新待办/提醒
当需要为用户创建新的待办或提醒时：

[SUGGESTED_TODO]
{{
  "title": "5:50起床准备出发",
  "description": "提醒准备乘坐网约车前往机场",
  "event_date_time": "2025-12-05T05:50:00",
  "duration": 600,
  "location": null,
  "relation_type": "sub"
}}
[/SUGGESTED_TODO]

### 2. 更新待办内容
当需要完善待办内容时：

[TODO_CONTENT_UPDATE]
## 12月5日北京出差

**基本信息**
- 时间：12月5日上午9:00
- 出发地：重庆江北国际机场
- 目的地：北京
- 天气：晴，5-12℃

**准备清单**
- [ ] 身份证件
- [ ] 工作资料
- [ ] 换洗衣物
- [ ] 电子设备及充电器

**行程安排**
- 05:50 起床准备
- 06:00 网约车接驾
- 07:00 到达机场
- 09:00 航班起飞
[/TODO_CONTENT_UPDATE]

### 3. 生成富媒体卡片
当查询到信息需要展示时（如天气、航班等）：

[RICH_CARD]
{{
  "card_type": "weather",
  "title": "北京天气",
  "subtitle": "12月5日",
  "data": {{
    "city": "北京",
    "date": "2025-12-05",
    "weather": "晴",
    "temperature": "5-12℃",
    "wind": "北风3级"
  }},
  "source": "天气查询"
}}
[/RICH_CARD]

## 🚫 禁止事项

1. **不要只是给建议而不行动**：能查询的立即查询，能创建的立即创建
2. **不要询问是否需要帮助**：直接提出具体的行动计划
3. **不要遗漏关键信息**：天气、交通、时间等都要考虑到
4. **不要只回复文字**：要生成结构化的待办和卡片

## 🎯 核心原则

1. **主动执行**：能做的事情立即做，不要只是建议
2. **完整规划**：考虑事项的所有相关需求
3. **结构化输出**：使用指定格式输出待办和卡片
4. **友好专业**：像贴心的私人助理一样服务

当前时间：{current_time}
"""


class TodoChatAgent(ReActChat):
    """
    待办聊天Agent
    
    使用ReAct架构进行任务规划和执行
    """
    
    def __init__(self,
                 function_list: Optional[List[Union[str, Dict, BaseTool]]] = None,
                 llm: Optional[Union[Dict, BaseChatModel]] = None,
                 **kwargs):
        
        # 默认工具列表
        if function_list is None:
            function_list = self._get_default_tools()
        
        # 默认LLM配置
        if llm is None:
            try:
                llm_config = get_llm_config()
                logger.info(f"🤖 TodoChatAgent 使用模型: {llm_config.get('model', 'unknown')}")
                llm = get_chat_model(llm_config)
            except ValueError as e:
                logger.warning(f"⚠️ LLM配置未就绪: {e}, 将在实际调用时重新初始化")
                # 创建一个空的LLM配置，稍后会重新初始化
                llm_config = {
                    'model_type': 'qwen_dashscope',
                    'model': 'qwen-turbo'
                }
                llm = llm_config  # 传递配置字典，让基类处理
        
        # 系统提示词
        system_message = TODO_CHAT_SYSTEM_PROMPT.format(
            current_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )
        
        super().__init__(
            function_list=function_list,
            llm=llm,
            system_message=system_message,
            name="待办助手",
            description="专门用于待办页面的智能聊天助手",
            **kwargs
        )
        
        logger.info("✅ TodoChatAgent 初始化完成")
    
    def _get_default_tools(self) -> List[Union[str, Dict, BaseTool]]:
        """获取默认工具列表（从工具注册中心获取，与TYMemoryAgent保持一致）"""
        try:
            from ty_mem_agent.mcp_integrations import get_tool_registry
            
            # 从工具注册中心获取所有已初始化的工具
            registry = get_tool_registry()
            
            # 检查工具注册中心是否已初始化
            if not registry._initialized or not registry.tools_cache:
                logger.warning("⚠️ 工具注册中心未初始化或工具缓存为空")
                logger.warning("   TodoChatAgent 将在没有工具的情况下运行")
                logger.warning("   这意味着无法查询天气、创建日程等")
                return []
            
            # 获取所有工具（不做过滤，与TYMemoryAgent保持一致）
            tools = registry.get_all_tools()
            
            if tools:
                logger.info(f"✅ TodoChatAgent 从工具注册中心获取到 {len(tools)} 个工具")
                tool_names = [getattr(t, 'name', 'unknown') for t in tools]
                logger.debug(f"   工具列表: {', '.join(tool_names)}")
            else:
                logger.warning("⚠️ 工具注册中心未返回任何工具")
            
            return tools
            
        except Exception as e:
            logger.error(f"❌ TodoChatAgent 从工具注册中心获取工具失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            logger.error("   Agent 将在没有工具的情况下运行")
            return []
    
    def chat(self,
             user_message: str,
             todo_content: Optional[str] = None,
             rich_cards: Optional[List[Dict]] = None,
             history: Optional[List[Dict]] = None) -> str:
        """
        同步聊天方法
        
        Args:
            user_message: 用户消息
            todo_content: 当前待办正文内容
            rich_cards: 关联的富媒体卡片
            history: 对话历史
            
        Returns:
            AI回复内容
        """
        import asyncio
        
        # 尝试获取或创建事件循环
        try:
            loop = asyncio.get_running_loop()
            # 如果在异步上下文中，创建task
            future = asyncio.ensure_future(
                self.chat_async(user_message, todo_content, rich_cards, history)
            )
            return loop.run_until_complete(future)
        except RuntimeError:
            # 没有运行的事件循环，创建新的
            return asyncio.run(
                self.chat_async(user_message, todo_content, rich_cards, history)
            )
    
    async def chat_async(self,
                         user_message: str,
                         todo_content: Optional[str] = None,
                         rich_cards: Optional[List[Dict]] = None,
                         history: Optional[List[Dict]] = None) -> str:
        """
        异步聊天方法
        
        Args:
            user_message: 用户消息
            todo_content: 当前待办正文内容
            rich_cards: 关联的富媒体卡片
            history: 对话历史
            
        Returns:
            AI回复内容
        """
        # 构建上下文消息
        messages = self._build_context_messages(
            user_message=user_message,
            todo_content=todo_content,
            rich_cards=rich_cards,
            history=history
        )
        
        # 调用ReAct运行
        full_response = ""
        try:
            for response in self._run(messages, lang='zh'):
                if response and len(response) > 0:
                    full_response = response[-1].content
        except Exception as e:
            logger.error(f"❌ TodoChatAgent 运行失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            full_response = f"抱歉，处理您的请求时遇到了问题: {str(e)}"
        
        return full_response
    
    def _build_context_messages(self,
                                user_message: str,
                                todo_content: Optional[str] = None,
                                rich_cards: Optional[List[Dict]] = None,
                                history: Optional[List[Dict]] = None) -> List[Message]:
        """
        构建带上下文的消息列表
        """
        messages = []
        
        # 构建上下文信息
        context_parts = []
        
        if todo_content:
            context_parts.append(f"## 当前待办正文\n\n{todo_content}")
        
        if rich_cards:
            cards_info = "\n".join([
                f"- {card.get('card_type', 'unknown')}: {card.get('title', '未知')}"
                for card in rich_cards
            ])
            context_parts.append(f"## 关联的富媒体卡片\n\n{cards_info}")
        
        context_message = "\n\n".join(context_parts) if context_parts else ""
        
        # 添加历史消息
        if history:
            for msg in history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    messages.append(Message(role=USER, content=content))
                elif role == "assistant":
                    messages.append(Message(role=ASSISTANT, content=content))
        
        # 构建当前用户消息（包含上下文）
        if context_message:
            full_user_message = f"""---
### 上下文信息

{context_message}

---

### 用户消息

{user_message}"""
        else:
            full_user_message = user_message
        
        messages.append(Message(role=USER, content=full_user_message))
        
        return messages
    
    def generate_session_title(self, user_message: str, max_length: int = 20) -> str:
        """
        基于用户初始消息生成会话标题
        
        Args:
            user_message: 用户消息
            max_length: 标题最大长度
            
        Returns:
            会话标题
        """
        try:
            # 使用LLM生成标题
            prompt = f"""请为以下用户消息生成一个简短的会话标题（不超过{max_length}个字符）：

用户消息: {user_message}

要求：
1. 标题要简洁明了，概括用户意图
2. 不要使用标点符号
3. 直接输出标题，不要有任何解释

标题："""
            
            messages = [Message(role=USER, content=prompt)]
            
            # 同步调用LLM
            response = ""
            for output in self.llm.chat(messages=messages):
                if output and len(output) > 0:
                    response = output[-1].content
            
            # 清理标题
            title = response.strip()
            # 去除可能的引号
            title = title.strip('"\'')
            # 截断到最大长度
            if len(title) > max_length:
                title = title[:max_length-3] + "..."
            
            return title if title else self._fallback_title(user_message, max_length)
            
        except Exception as e:
            logger.warning(f"⚠️ 生成标题失败，使用回退方案: {e}")
            return self._fallback_title(user_message, max_length)
    
    def _fallback_title(self, user_message: str, max_length: int = 20) -> str:
        """回退标题生成方案"""
        # 简单截取用户消息前N个字符
        title = user_message.strip()
        # 去除换行符
        title = title.replace('\n', ' ').replace('\r', '')
        if len(title) > max_length:
            title = title[:max_length-3] + "..."
        return title if title else "新对话"
    
    def parse_response(self, response: str) -> Dict[str, Any]:
        """
        解析AI回复，提取结构化内容
        
        处理ReAct格式的回复，提取Final Answer作为主要内容
        
        Returns:
            {
                "content": "纯文本回复内容",
                "todo_content": "更新后的待办内容（如果有）",
                "suggested_todos": [建议的新待办列表],
                "rich_cards": [富媒体卡片列表]
            }
        """
        import re
        
        # 首先处理ReAct格式：提取Final Answer
        # ReAct格式：Thought: ... Action: ... Observation: ... Final Answer: ...
        final_answer_match = re.search(
            r'Final Answer:\s*(.*?)$',
            response,
            re.DOTALL | re.IGNORECASE
        )
        
        if final_answer_match:
            # 找到Final Answer，使用它作为主要内容
            clean_response = final_answer_match.group(1).strip()
            logger.debug(f"📝 从ReAct回复中提取Final Answer: {clean_response[:100]}...")
        else:
            # 没有Final Answer格式，尝试去除Thought:前缀
            clean_response = response
            # 去除开头的Thought:部分（如果存在）
            thought_pattern = r'^Thought:\s*.*?(?=\n\n|\n[A-Z]|$)'
            clean_response = re.sub(thought_pattern, '', clean_response, flags=re.DOTALL).strip()
        
        result = {
            "content": clean_response,
            "todo_content": None,
            "suggested_todos": [],
            "rich_cards": []
        }
        
        todo_match = re.search(
            r'\[TODO_CONTENT_UPDATE\](.*?)\[/TODO_CONTENT_UPDATE\]',
            response,
            re.DOTALL
        )
        if todo_match:
            result["todo_content"] = todo_match.group(1).strip()
            # 从回复中移除这部分
            result["content"] = response.replace(todo_match.group(0), '').strip()
        
        # 提取建议的新待办
        suggested_matches = re.findall(
            r'\[SUGGESTED_TODO\](.*?)\[/SUGGESTED_TODO\]',
            response,
            re.DOTALL
        )
        for match in suggested_matches:
            try:
                todo_data = json.loads(match.strip())
                result["suggested_todos"].append(todo_data)
                result["content"] = result["content"].replace(f'[SUGGESTED_TODO]{match}[/SUGGESTED_TODO]', '').strip()
            except json.JSONDecodeError:
                logger.warning(f"⚠️ 无法解析建议待办: {match}")
        
        # 提取富媒体卡片
        card_matches = re.findall(
            r'\[RICH_CARD\](.*?)\[/RICH_CARD\]',
            response,
            re.DOTALL
        )
        for match in card_matches:
            try:
                card_data = json.loads(match.strip())
                result["rich_cards"].append(card_data)
                result["content"] = result["content"].replace(f'[RICH_CARD]{match}[/RICH_CARD]', '').strip()
            except json.JSONDecodeError:
                logger.warning(f"⚠️ 无法解析富媒体卡片: {match}")
        
        # 清理残留的标记和多余空行
        result["content"] = re.sub(r'\n{3,}', '\n\n', result["content"])
        result["content"] = result["content"].strip()
        
        return result


# 全局Agent实例管理
_todo_chat_agent_instance = None


def get_todo_chat_agent(force_reinit: bool = False) -> TodoChatAgent:
    """
    获取TodoChatAgent实例
    
    Args:
        force_reinit: 是否强制重新初始化（用于工具注册后重新获取）
    """
    global _todo_chat_agent_instance
    
    if _todo_chat_agent_instance is None or force_reinit:
        logger.info("🔧 初始化 TodoChatAgent...")
        _todo_chat_agent_instance = TodoChatAgent()
        
        # 检查工具是否已加载
        if hasattr(_todo_chat_agent_instance, 'function_map'):
            tool_count = len(_todo_chat_agent_instance.function_map)
            if tool_count > 0:
                logger.info(f"✅ TodoChatAgent 已加载 {tool_count} 个工具")
                tool_names = list(_todo_chat_agent_instance.function_map.keys())[:10]
                logger.info(f"   部分工具: {', '.join(tool_names)}...")
            else:
                logger.warning("⚠️ TodoChatAgent 没有加载到任何工具！")
                logger.warning("   请确保 MCP 工具已正确初始化")
    
    return _todo_chat_agent_instance


def reset_todo_chat_agent():
    """重置TodoChatAgent实例（用于工具更新后重新初始化）"""
    global _todo_chat_agent_instance
    _todo_chat_agent_instance = None
    logger.info("🔄 TodoChatAgent 实例已重置")

