#!/usr/bin/env python3
"""
MultiAgentRouter - 多Agent路由器

智能分发用户请求到合适的Agent：
- TYMemoryAgent: 通用对话、待办管理、工具调用
- TodoChatAgent: 待办页面专用聊天
- PhoneAgent: 手机APP操作任务

采用 Router 模式实现，保持各 Agent 的 Prompt 独立，便于扩展
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional, Union

from loguru import logger

# 添加路径支持
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from qwen_agent.agent import Agent
from qwen_agent.llm import get_chat_model, BaseChatModel
from qwen_agent.llm.schema import Message, ASSISTANT, USER, SYSTEM

from ty_mem_agent.config.settings import get_llm_config


class AgentType(Enum):
    """Agent 类型"""
    MEMORY_AGENT = "memory_agent"      # 通用记忆Agent
    TODO_CHAT_AGENT = "todo_chat_agent"  # 待办聊天Agent
    PHONE_AGENT = "phone_agent"        # 手机操作Agent


@dataclass
class RoutingResult:
    """路由结果"""
    target_agent: AgentType
    confidence: float
    reason: str
    extracted_info: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_agent": self.target_agent.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "extracted_info": self.extracted_info
        }


# 路由决策的系统提示词
ROUTER_SYSTEM_PROMPT = """你是一个智能路由决策器，负责分析用户请求并决定由哪个Agent来处理。

## 可用的Agent

1. **memory_agent** (通用记忆Agent)
   - 适用场景：日常对话、问答、查询天气、查询时间、管理待办事项、导航规划等
   - 关键特征：普通聊天、信息查询、使用MCP工具

2. **todo_chat_agent** (待办聊天Agent)
   - 适用场景：针对特定待办事项的讨论和完善
   - 关键特征：用户在待办详情页发起的聊天、补充待办内容、生成子任务
   - 注意：这个场景通常有明确的待办上下文

3. **phone_agent** (手机操作Agent)
   - 适用场景：需要在手机APP上执行操作的任务
   - 关键词：订票、买票、预订、下单、购买、加购物车、点外卖、叫车、打车
   - 具体场景：
     * 火车票/高铁票预订 → "帮我订明天去北京的高铁票"
     * 机票预订 → "帮我订下周五飞上海的机票"
     * 酒店预订 → "帮我订杭州的酒店"
     * 网购下单 → "帮我在淘宝买双袜子"、"帮我在京东下单一个充电宝"
     * 外卖订餐 → "帮我点一杯奶茶"、"帮我在美团点个外卖"
     * 网约车 → "帮我叫个车去机场"、"预约明天早上6点的滴滴"

## 判断规则

1. **优先判断是否是手机操作任务**：
   - 如果用户明确要求"订"、"买"、"下单"、"购买"、"预订"等动作性词汇
   - 且涉及火车票、机票、酒店、商品、外卖、网约车等
   - → 路由到 phone_agent

2. **判断是否是待办相关**：
   - 如果用户在讨论某个具体的待办事项
   - 或者需要补充、完善待办内容
   - → 路由到 todo_chat_agent（但需要有待办上下文）

3. **其他情况**：
   - 普通问答、信息查询、工具使用
   - → 路由到 memory_agent

## 特殊情况

- 如果用户说"帮我添加一个待办"而不是"帮我订xxx" → memory_agent（创建待办，不是执行购买）
- 如果用户说"查询明天北京的天气" → memory_agent（信息查询）
- 如果用户说"帮我在12306订票" → phone_agent（需要操作APP）
- 如果用户说"有什么航班从北京到上海" → memory_agent（信息查询，不是购买）
- 如果用户说"帮我买张明天北京到上海的机票" → phone_agent（需要购买操作）

## 输出格式

请严格按以下JSON格式输出：

```json
{
  "target_agent": "phone_agent",
  "confidence": 0.95,
  "reason": "用户要求订购火车票，需要在12306 APP上操作",
  "is_action_required": true,
  "action_type": "train_ticket"
}
```

其中：
- target_agent: 必须是 memory_agent / todo_chat_agent / phone_agent 之一
- confidence: 0-1之间的置信度
- reason: 简短说明选择理由
- is_action_required: 是否需要执行动作（购买/预订等）
- action_type: 动作类型（可选，仅phone_agent需要）
"""


class MultiAgentRouter(Agent):
    """
    多Agent路由器
    
    智能分析用户请求，路由到合适的Agent处理：
    - 保持各Agent的Prompt独立
    - 支持动态扩展新Agent
    - 提供统一的入口
    """
    
    def __init__(
        self,
        llm: Optional[Union[Dict, BaseChatModel]] = None,
        name: str = "智能路由器",
        description: str = None,
        use_keyword_routing: bool = True,
        **kwargs
    ):
        """
        初始化路由器
        
        Args:
            llm: LLM 配置或实例
            name: 路由器名称
            description: 描述
            use_keyword_routing: 是否使用关键词快速路由（优先于LLM路由）
        """
        if description is None:
            description = "智能分析用户请求，路由到合适的Agent处理"
        
        # 默认 LLM 配置
        if llm is None:
            try:
                llm_config = get_llm_config()
                llm = get_chat_model(llm_config)
            except ValueError as e:
                logger.warning(f"⚠️ LLM 配置未就绪: {e}")
                llm_config = {
                    'model_type': 'qwen_dashscope',
                    'model': 'qwen-turbo'
                }
                llm = llm_config
        
        super().__init__(
            llm=llm,
            name=name,
            description=description,
            **kwargs
        )
        
        self.use_keyword_routing = use_keyword_routing
        
        # Agent 实例缓存
        self._agents: Dict[AgentType, Agent] = {}
        
        logger.info(f"✅ MultiAgentRouter 初始化完成")
        logger.info(f"   关键词快速路由: {use_keyword_routing}")
    
    def _run(self, messages: List[Message], lang: str = 'zh', **kwargs) -> Iterator[List[Message]]:
        """
        运行路由器
        
        分析消息并决定路由，但不实际执行Agent
        """
        # 构建系统提示词
        system_message = Message(role=SYSTEM, content=ROUTER_SYSTEM_PROMPT)
        enhanced_messages = [system_message] + messages
        
        # 调用 LLM 进行路由决策
        response = ""
        for chunk in self.llm.chat(messages=enhanced_messages):
            if chunk and len(chunk) > 0:
                response = chunk[-1].content
        
        yield [Message(role=ASSISTANT, content=response)]
    
    def _keyword_route(self, query: str) -> Optional[RoutingResult]:
        """
        基于关键词的快速路由
        
        优先于 LLM 路由，处理明显的场景
        """
        query_lower = query.lower()
        
        # 手机操作关键词模式
        phone_patterns = [
            # 火车票
            (r'(订|买|预订|预约|购买).*(火车|高铁|动车|火车票)', 'train_ticket'),
            (r'(帮我|给我).*(订|买).*(火车|高铁|动车)', 'train_ticket'),
            (r'12306.*(订|买|预订)', 'train_ticket'),
            
            # 机票
            (r'(订|买|预订|预约|购买).*(机票|飞机|航班)', 'flight_ticket'),
            (r'(帮我|给我).*(订|买).*(机票|飞机)', 'flight_ticket'),
            
            # 酒店
            (r'(订|预订|预约).*(酒店|住宿|宾馆|民宿)', 'hotel'),
            
            # 网购
            (r'(在|用|打开).*(淘宝|京东|拼多多|天猫).*(买|下单|购买|搜索)', 'shopping'),
            (r'(帮我|给我).*(买|下单|购买).*(袜子|衣服|商品|东西)', 'shopping'),
            (r'(加入|加到|放入).*(购物车)', 'shopping'),
            
            # 外卖
            (r'(点|订|叫).*(外卖|奶茶|咖啡|餐|饭|吃的)', 'food_delivery'),
            (r'(在|用|打开).*(美团|饿了么).*(点|订|买)', 'food_delivery'),
            
            # 网约车
            (r'(叫|打|预约|预订|订).*(车|滴滴|出租车|网约车|专车|快车)', 'ride_hailing'),
            (r'(帮我|给我).*(叫|打|预约).*(车|滴滴)', 'ride_hailing'),
        ]
        
        for pattern, action_type in phone_patterns:
            if re.search(pattern, query):
                logger.info(f"🎯 关键词路由命中: {action_type}")
                return RoutingResult(
                    target_agent=AgentType.PHONE_AGENT,
                    confidence=0.9,
                    reason=f"关键词匹配: {action_type}",
                    extracted_info={"action_type": action_type}
                )
        
        # 排除词检测（这些应该走 memory_agent）
        exclude_patterns = [
            r'(查询|查看|有.*航班|有.*火车|什么时候|多少钱)',  # 纯查询
            r'(添加|创建|新建).*(待办|提醒|日程)',  # 创建待办
            r'(天气|时间|日期)',  # 信息查询
        ]
        
        for pattern in exclude_patterns:
            if re.search(pattern, query):
                return RoutingResult(
                    target_agent=AgentType.MEMORY_AGENT,
                    confidence=0.8,
                    reason="信息查询或待办管理任务",
                    extracted_info={}
                )
        
        return None
    
    async def route(
        self,
        query: str,
        context: Dict[str, Any] = None
    ) -> RoutingResult:
        """
        路由决策
        
        Args:
            query: 用户查询
            context: 上下文信息（如当前是否在待办页面）
        
        Returns:
            RoutingResult: 路由结果
        """
        context = context or {}
        
        logger.info(f"🔀 路由分析: {query[:50]}...")
        
        # 1. 检查上下文（如果在待办聊天页面，优先使用 todo_chat_agent）
        if context.get("is_todo_chat_page") and context.get("event_id"):
            logger.info("📋 检测到待办聊天上下文，使用 todo_chat_agent")
            return RoutingResult(
                target_agent=AgentType.TODO_CHAT_AGENT,
                confidence=1.0,
                reason="在待办聊天页面，使用专用Agent",
                extracted_info={"event_id": context.get("event_id")}
            )
        
        # 2. 关键词快速路由
        if self.use_keyword_routing:
            keyword_result = self._keyword_route(query)
            if keyword_result:
                return keyword_result
        
        # 3. LLM 路由
        messages = [Message(role=USER, content=query)]
        
        response = ""
        for chunk in self._run(messages):
            if chunk and len(chunk) > 0:
                response = chunk[-1].content
        
        # 4. 解析 LLM 结果
        try:
            import json
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                result = json.loads(json_match.group())
                target = result.get("target_agent", "memory_agent")
                
                # 映射到 AgentType
                agent_type_map = {
                    "memory_agent": AgentType.MEMORY_AGENT,
                    "todo_chat_agent": AgentType.TODO_CHAT_AGENT,
                    "phone_agent": AgentType.PHONE_AGENT,
                }
                
                target_agent = agent_type_map.get(target, AgentType.MEMORY_AGENT)
                
                return RoutingResult(
                    target_agent=target_agent,
                    confidence=result.get("confidence", 0.7),
                    reason=result.get("reason", "LLM 路由决策"),
                    extracted_info={
                        "is_action_required": result.get("is_action_required", False),
                        "action_type": result.get("action_type")
                    }
                )
        except Exception as e:
            logger.warning(f"⚠️ 解析路由结果失败: {e}")
        
        # 5. 默认使用 memory_agent
        return RoutingResult(
            target_agent=AgentType.MEMORY_AGENT,
            confidence=0.5,
            reason="默认路由到通用Agent",
            extracted_info={}
        )
    
    def get_agent(self, agent_type: AgentType) -> Optional[Agent]:
        """
        获取指定类型的 Agent 实例
        
        Args:
            agent_type: Agent 类型
        
        Returns:
            Agent 实例
        """
        if agent_type in self._agents:
            return self._agents[agent_type]
        
        # 延迟加载 Agent
        try:
            if agent_type == AgentType.MEMORY_AGENT:
                from ty_mem_agent.agents.ty_memory_agent import TYMemoryAgent
                agent = TYMemoryAgent()
                self._agents[agent_type] = agent
                
            elif agent_type == AgentType.TODO_CHAT_AGENT:
                from ty_mem_agent.agents.todo_chat_agent import TodoChatAgent
                agent = TodoChatAgent()
                self._agents[agent_type] = agent
                
            elif agent_type == AgentType.PHONE_AGENT:
                from ty_mem_agent.agents.phone_agent import PhoneAgent
                agent = PhoneAgent()
                self._agents[agent_type] = agent
            
            return self._agents.get(agent_type)
            
        except Exception as e:
            logger.error(f"❌ 加载 Agent 失败: {agent_type.value}, 错误: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    async def handle_request(
        self,
        query: str,
        user_id: str = None,
        session_id: str = None,
        context: Dict[str, Any] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        处理用户请求（完整流程）
        
        1. 路由决策
        2. 获取目标Agent
        3. 执行请求
        4. 返回结果
        
        Args:
            query: 用户查询
            user_id: 用户 ID
            session_id: 会话 ID
            context: 上下文
            **kwargs: 其他参数
        
        Returns:
            处理结果
        """
        context = context or {}
        
        # 1. 路由决策
        routing_result = await self.route(query, context)
        
        logger.info(f"🔀 路由结果: {routing_result.target_agent.value} (置信度: {routing_result.confidence:.2f})")
        logger.info(f"   原因: {routing_result.reason}")
        
        # 2. 获取目标 Agent
        target_agent = self.get_agent(routing_result.target_agent)
        
        if not target_agent:
            return {
                "success": False,
                "error": f"无法加载 Agent: {routing_result.target_agent.value}",
                "routing": routing_result.to_dict()
            }
        
        # 3. 根据不同 Agent 类型执行请求
        try:
            if routing_result.target_agent == AgentType.PHONE_AGENT:
                # PhoneAgent 有专门的 handle_query 方法
                result = await target_agent.handle_query(
                    user_query=query,
                    user_id=user_id,
                    execute=True
                )
                return {
                    "success": True,
                    "agent_type": routing_result.target_agent.value,
                    "routing": routing_result.to_dict(),
                    "result": result
                }
            
            elif routing_result.target_agent == AgentType.TODO_CHAT_AGENT:
                # TodoChatAgent
                response = await target_agent.chat_async(
                    user_message=query,
                    todo_content=context.get("todo_content"),
                    rich_cards=context.get("rich_cards"),
                    history=context.get("history")
                )
                
                # 解析响应
                parsed = target_agent.parse_response(response)
                
                return {
                    "success": True,
                    "agent_type": routing_result.target_agent.value,
                    "routing": routing_result.to_dict(),
                    "result": {
                        "content": parsed.get("content", response),
                        "todo_content": parsed.get("todo_content"),
                        "suggested_todos": parsed.get("suggested_todos", []),
                        "rich_cards": parsed.get("rich_cards", [])
                    }
                }
            
            else:
                # TYMemoryAgent
                from qwen_agent.llm.schema import Message, USER
                
                messages = [Message(role=USER, content=query)]
                
                response_content = ""
                async for chunk in target_agent.run_with_memory(
                    messages=messages,
                    user_id=user_id or "default_user",
                    session_id=session_id or "default_session",
                    **kwargs
                ):
                    if chunk and len(chunk) > 0:
                        response_content = chunk[-1].content
                
                return {
                    "success": True,
                    "agent_type": routing_result.target_agent.value,
                    "routing": routing_result.to_dict(),
                    "result": {
                        "content": response_content
                    }
                }
                
        except Exception as e:
            logger.error(f"❌ Agent 执行失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            return {
                "success": False,
                "agent_type": routing_result.target_agent.value,
                "routing": routing_result.to_dict(),
                "error": str(e)
            }
    
    def get_registered_agents(self) -> List[Dict[str, Any]]:
        """获取已注册的 Agent 列表"""
        agents_info = []
        
        for agent_type in AgentType:
            agent = self._agents.get(agent_type)
            agents_info.append({
                "type": agent_type.value,
                "loaded": agent is not None,
                "name": agent.name if agent else None,
                "description": agent.description if agent else None
            })
        
        return agents_info


# 全局路由器实例
_router_instance: Optional[MultiAgentRouter] = None


def get_multi_agent_router(force_reinit: bool = False) -> MultiAgentRouter:
    """获取 MultiAgentRouter 单例"""
    global _router_instance
    
    if _router_instance is None or force_reinit:
        logger.info("🔧 初始化 MultiAgentRouter...")
        _router_instance = MultiAgentRouter()
    
    return _router_instance


def reset_multi_agent_router():
    """重置 MultiAgentRouter"""
    global _router_instance
    _router_instance = None
    logger.info("🔄 MultiAgentRouter 已重置")

