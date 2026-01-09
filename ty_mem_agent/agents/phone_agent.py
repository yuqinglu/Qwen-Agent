#!/usr/bin/env python3
"""
PhoneAgent - 手机操作智能代理

基于 Open-AutoGLM 实现手机 APP 操作能力
支持订票、购物、打车等需要操作手机 APP 的任务
"""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

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
from ty_mem_agent.phone_integration import get_autoglm_client, get_device_manager


class PhoneTaskType(Enum):
    """手机任务类型"""
    TRAIN_TICKET = "train_ticket"      # 火车票
    FLIGHT_TICKET = "flight_ticket"    # 机票
    HOTEL = "hotel"                    # 酒店
    SHOPPING = "shopping"              # 购物
    FOOD_DELIVERY = "food_delivery"    # 外卖
    RIDE_HAILING = "ride_hailing"      # 网约车
    OTHER = "other"                    # 其他


@dataclass
class PhoneTaskInfo:
    """手机任务信息"""
    task_type: PhoneTaskType
    app_name: str
    task_description: str
    parameters: Dict[str, Any]
    original_query: str


# 手机操作Agent的系统提示词
PHONE_AGENT_SYSTEM_PROMPT = """你是一个专门负责分析手机APP操作任务的智能助理。

## 你的职责

分析用户的需求，判断是否需要操作手机APP，并提取关键信息。

## 支持的任务类型

1. **火车票预订** (train_ticket)
   - 关键词：火车、高铁、动车、火车票、12306
   - APP：12306
   - 需提取：出发地、目的地、日期、时间偏好、座位类型

2. **机票预订** (flight_ticket)
   - 关键词：飞机、机票、航班、飞往
   - APP：携程、飞猪、去哪儿
   - 需提取：出发地、目的地、日期、舱位偏好

3. **酒店预订** (hotel)
   - 关键词：酒店、住宿、预订房间
   - APP：携程、美团、飞猪
   - 需提取：城市、入住日期、离店日期、房型偏好

4. **网购下单** (shopping)
   - 关键词：买、购买、下单、加购物车、淘宝、京东、拼多多
   - APP：淘宝、京东、拼多多
   - 需提取：商品描述、数量、价格偏好

5. **外卖订餐** (food_delivery)
   - 关键词：外卖、点餐、奶茶、咖啡、美团、饿了么
   - APP：美团、饿了么
   - 需提取：食品描述、数量、配送地址

6. **网约车** (ride_hailing)
   - 关键词：打车、叫车、网约车、滴滴、预约用车
   - APP：滴滴、高德
   - 需提取：出发地、目的地、用车时间

## 输出格式

请按以下JSON格式输出分析结果：

```json
{
  "is_phone_task": true,
  "task_type": "train_ticket",
  "app_name": "12306",
  "task_description": "在12306预订明天从重庆到昆明的高铁票",
  "parameters": {
    "departure": "重庆",
    "destination": "昆明",
    "date": "明天",
    "train_type": "高铁",
    "seat_class": null
  },
  "confidence": 0.95,
  "missing_info": [],
  "clarification_needed": false
}
```

如果不是手机操作任务：

```json
{
  "is_phone_task": false,
  "reason": "这是一个普通的问答任务，不需要操作手机APP"
}
```

## 注意事项

1. 只有明确需要在手机APP上操作的任务才返回 is_phone_task: true
2. 如果信息不完整，列出缺失的信息并设置 clarification_needed: true
3. 生成的 task_description 应该是可以直接交给 AutoGLM 执行的自然语言指令
4. 当前时间：{current_time}
"""


class PhoneAgent(Agent):
    """
    手机操作智能代理
    
    专门处理需要操作手机APP的任务，如：
    - 订火车票/机票
    - 网购下单
    - 点外卖
    - 预约网约车
    
    使用 Open-AutoGLM 来执行实际的手机操作
    """
    
    def __init__(
        self,
        llm: Optional[Union[Dict, BaseChatModel]] = None,
        name: str = "手机操作助理",
        description: str = None,
        **kwargs
    ):
        """
        初始化手机操作Agent
        
        Args:
            llm: LLM 配置或实例
            name: Agent 名称
            description: Agent 描述
        """
        if description is None:
            description = (
                "专门负责手机APP操作的智能助理，可以帮助用户订票、购物、点外卖等。"
                "操作会在云端虚拟手机上执行，最终支付需要用户在真实手机上完成。"
            )
        
        # 默认 LLM 配置
        if llm is None:
            try:
                llm_config = get_llm_config()
                logger.info(f"🤖 PhoneAgent 使用模型: {llm_config.get('model', 'unknown')}")
                llm = get_chat_model(llm_config)
            except ValueError as e:
                logger.warning(f"⚠️ LLM 配置未就绪: {e}")
                llm_config = {
                    'model_type': 'qwen_dashscope',
                    'model': 'qwen-turbo'
                }
                llm = llm_config
        
        # 初始化父类（Agent 不需要 function_list 参数）
        super().__init__(
            llm=llm,
            name=name,
            description=description,
            **kwargs
        )
        
        # AutoGLM 客户端
        self.autoglm_client = get_autoglm_client()
        
        # 设备管理器
        self.device_manager = get_device_manager()
        
        # 当前用户上下文
        self.current_user_id: Optional[str] = None
        
        logger.info(f"✅ PhoneAgent 初始化完成: {self.name}")
        logger.info(f"   AutoGLM 可用: {self.autoglm_client.is_available()}")
    
    def _run(self, messages: List[Message], lang: str = 'zh', **kwargs):
        """
        运行 Agent（同步生成器）
        
        这是 Agent 基类要求实现的方法
        """
        # 构建系统提示词
        system_prompt = PHONE_AGENT_SYSTEM_PROMPT.format(
            current_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )
        
        # 添加系统消息
        enhanced_messages = [Message(role=SYSTEM, content=system_prompt)] + messages
        
        # 调用 LLM 分析任务
        response = ""
        for chunk in self.llm.chat(messages=enhanced_messages):
            if chunk and len(chunk) > 0:
                response = chunk[-1].content
        
        # 返回分析结果
        yield [Message(role=ASSISTANT, content=response)]
    
    async def analyze_task(self, user_query: str) -> Dict[str, Any]:
        """
        分析用户查询，判断是否是手机操作任务
        
        Args:
            user_query: 用户查询
        
        Returns:
            分析结果，包含任务类型、APP、参数等
        """
        logger.info(f"📱 分析手机任务: {user_query[:50]}...")
        
        messages = [Message(role=USER, content=user_query)]
        
        # 调用 _run 获取分析结果
        response = ""
        for chunk in self._run(messages):
            if chunk and len(chunk) > 0:
                response = chunk[-1].content
        
        # 解析 JSON 结果
        try:
            # 提取 JSON 部分
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                import json
                result = json.loads(json_match.group())
                logger.info(f"✅ 任务分析完成: is_phone_task={result.get('is_phone_task')}")
                return result
            else:
                logger.warning("⚠️ 未能从响应中提取 JSON")
                return {
                    "is_phone_task": False,
                    "reason": "无法解析分析结果",
                    "raw_response": response
                }
        except Exception as e:
            logger.error(f"❌ 解析分析结果失败: {e}")
            return {
                "is_phone_task": False,
                "reason": f"解析失败: {str(e)}",
                "raw_response": response
            }
    
    async def execute_phone_task(
        self,
        task_info: Dict[str, Any],
        user_id: str = None
    ) -> Dict[str, Any]:
        """
        执行手机操作任务
        
        Args:
            task_info: 任务信息（来自 analyze_task 的结果）
            user_id: 用户 ID
        
        Returns:
            执行结果
        """
        if not task_info.get("is_phone_task"):
            return {
                "success": False,
                "message": "这不是一个手机操作任务",
                "error": task_info.get("reason", "未知原因")
            }
        
        task_description = task_info.get("task_description", "")
        app_name = task_info.get("app_name", "")
        
        logger.info(f"📱 执行手机任务: {task_description}")
        logger.info(f"   目标APP: {app_name}")
        logger.info(f"   用户: {user_id}")
        
        # 检查 AutoGLM 是否可用
        if not self.autoglm_client.is_available():
            return {
                "success": False,
                "message": "手机操作服务暂不可用",
                "error": "AutoGLM 服务未配置或不可用",
                "fallback_suggestion": self._generate_fallback_suggestion(task_info)
            }
        
        # 分配设备
        device = await self.device_manager.acquire_device(user_id or "default_user")
        
        if not device:
            return {
                "success": False,
                "message": "暂无可用设备，请稍后重试",
                "error": "没有可用的虚拟设备"
            }
        
        try:
            # 执行任务
            result = await self.autoglm_client.execute_task(
                task_description=task_description,
                device_id=device.device_id,
                app_hint=app_name
            )
            
            # 构建响应
            if result.success:
                return {
                    "success": True,
                    "message": self._format_success_message(task_info, result),
                    "task_id": result.task_id,
                    "app_name": app_name,
                    "steps": result.steps,
                    "duration_seconds": result.duration_seconds,
                    "next_action": self._generate_next_action(task_info)
                }
            else:
                return {
                    "success": False,
                    "message": result.message,
                    "task_id": result.task_id,
                    "error": result.error,
                    "fallback_suggestion": self._generate_fallback_suggestion(task_info)
                }
                
        finally:
            # 释放设备
            self.device_manager.release_device(device.device_id)
    
    def _format_success_message(
        self,
        task_info: Dict[str, Any],
        result: Any
    ) -> str:
        """格式化成功消息"""
        task_type = task_info.get("task_type", "other")
        app_name = task_info.get("app_name", "APP")
        
        base_message = f"✅ 已在云端手机上完成操作"
        
        type_messages = {
            "train_ticket": f"已在{app_name}上为您选好火车票，请在您的手机上打开{app_name}确认并支付。",
            "flight_ticket": f"已在{app_name}上为您选好机票，请在您的手机上打开{app_name}确认并支付。",
            "hotel": f"已在{app_name}上为您选好酒店，请在您的手机上打开{app_name}确认并支付。",
            "shopping": f"已将商品加入{app_name}购物车，请在您的手机上打开{app_name}确认并支付。",
            "food_delivery": f"已在{app_name}上为您选好外卖，请在您的手机上打开{app_name}确认并支付。",
            "ride_hailing": f"已在{app_name}上为您预约用车，请在您的手机上打开{app_name}确认订单。",
        }
        
        specific_message = type_messages.get(task_type, f"请在您的手机上打开{app_name}完成后续操作。")
        
        return f"{base_message}\n\n{specific_message}"
    
    def _generate_next_action(self, task_info: Dict[str, Any]) -> Dict[str, str]:
        """生成下一步操作提示"""
        app_name = task_info.get("app_name", "APP")
        task_type = task_info.get("task_type", "other")
        
        return {
            "action": "open_app",
            "app_name": app_name,
            "instruction": f"请打开您手机上的{app_name}，在购物车/订单页面确认并完成支付。",
            "warning": "请注意核对订单信息后再支付。"
        }
    
    def _generate_fallback_suggestion(self, task_info: Dict[str, Any]) -> str:
        """生成降级建议"""
        task_type = task_info.get("task_type", "other")
        params = task_info.get("parameters", {})
        
        suggestions = {
            "train_ticket": f"您可以手动打开12306 APP，搜索从{params.get('departure', '出发地')}到{params.get('destination', '目的地')}的{params.get('date', '日期')}车票。",
            "flight_ticket": f"您可以手动打开携程/飞猪 APP，搜索从{params.get('departure', '出发地')}到{params.get('destination', '目的地')}的{params.get('date', '日期')}机票。",
            "hotel": f"您可以手动打开携程/美团 APP，搜索{params.get('city', '城市')}的酒店。",
            "shopping": f"您可以手动打开淘宝/京东 APP，搜索{params.get('item', '商品')}。",
            "food_delivery": f"您可以手动打开美团/饿了么 APP，搜索{params.get('food', '食品')}。",
            "ride_hailing": f"您可以手动打开滴滴 APP，预约从{params.get('origin', '出发地')}到{params.get('destination', '目的地')}的行程。",
        }
        
        return suggestions.get(task_type, "请手动在对应APP中完成操作。")
    
    async def handle_query(
        self,
        user_query: str,
        user_id: str = None,
        execute: bool = True
    ) -> Dict[str, Any]:
        """
        处理用户查询（完整流程）
        
        Args:
            user_query: 用户查询
            user_id: 用户 ID
            execute: 是否执行任务（False 则只分析不执行）
        
        Returns:
            处理结果
        """
        # 1. 分析任务
        analysis = await self.analyze_task(user_query)
        
        # 2. 如果不是手机任务，直接返回
        if not analysis.get("is_phone_task"):
            return {
                "handled": False,
                "analysis": analysis,
                "message": analysis.get("reason", "这不是一个手机操作任务")
            }
        
        # 3. 如果需要澄清信息
        if analysis.get("clarification_needed"):
            return {
                "handled": True,
                "needs_clarification": True,
                "analysis": analysis,
                "missing_info": analysis.get("missing_info", []),
                "message": f"为了帮您完成任务，请补充以下信息：{', '.join(analysis.get('missing_info', []))}"
            }
        
        # 4. 如果不执行，只返回分析结果
        if not execute:
            return {
                "handled": True,
                "analysis": analysis,
                "message": f"已分析任务：{analysis.get('task_description')}"
            }
        
        # 5. 执行任务
        result = await self.execute_phone_task(analysis, user_id)
        
        return {
            "handled": True,
            "analysis": analysis,
            "execution_result": result,
            "message": result.get("message", "")
        }
    
    def get_capabilities(self) -> Dict[str, Any]:
        """获取 Agent 能力描述"""
        return {
            "name": self.name,
            "description": self.description,
            "supported_tasks": [
                {
                    "type": "train_ticket",
                    "description": "火车票预订",
                    "apps": ["12306"]
                },
                {
                    "type": "flight_ticket",
                    "description": "机票预订",
                    "apps": ["携程", "飞猪"]
                },
                {
                    "type": "hotel",
                    "description": "酒店预订",
                    "apps": ["携程", "美团", "飞猪"]
                },
                {
                    "type": "shopping",
                    "description": "网购下单",
                    "apps": ["淘宝", "京东", "拼多多"]
                },
                {
                    "type": "food_delivery",
                    "description": "外卖订餐",
                    "apps": ["美团", "饿了么"]
                },
                {
                    "type": "ride_hailing",
                    "description": "预约网约车",
                    "apps": ["滴滴", "高德"]
                }
            ],
            "autoglm_available": self.autoglm_client.is_available(),
            "device_status": self.device_manager.get_status_summary()
        }


# 全局 Agent 实例
_phone_agent_instance: Optional[PhoneAgent] = None


def get_phone_agent(force_reinit: bool = False) -> PhoneAgent:
    """获取 PhoneAgent 单例"""
    global _phone_agent_instance
    
    if _phone_agent_instance is None or force_reinit:
        logger.info("🔧 初始化 PhoneAgent...")
        _phone_agent_instance = PhoneAgent()
    
    return _phone_agent_instance


def reset_phone_agent():
    """重置 PhoneAgent 实例"""
    global _phone_agent_instance
    _phone_agent_instance = None
    logger.info("🔄 PhoneAgent 已重置")

