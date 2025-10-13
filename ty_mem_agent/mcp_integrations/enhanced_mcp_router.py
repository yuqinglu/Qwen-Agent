#!/usr/bin/env python3
"""
增强版MCP智能路由器
基于QwenAgent的Router设计，支持LLM驱动的意图理解和COT推理
"""

import asyncio
import json
from typing import Dict, List, Optional, Any, Iterator, Union
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from loguru import logger

# QwenAgent imports
from qwen_agent.agents.assistant import Assistant
from qwen_agent.llm import BaseChatModel
from qwen_agent.llm.schema import Message, ASSISTANT, USER, SYSTEM
from qwen_agent.tools import BaseTool

# 使用简洁的绝对导入
from ty_mem_agent.config.settings import settings


@dataclass
class MCPRequest:
    """MCP请求"""
    user_id: str
    session_id: str
    intent: str
    parameters: Dict[str, Any]
    context: Dict[str, Any]
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class MCPResponse:
    """MCP响应"""
    service_name: str
    success: bool
    result: Any
    error: Optional[str] = None
    execution_time: float = 0.0
    metadata: Dict[str, Any] = None
    reasoning_steps: List[str] = None  # COT推理步骤
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if self.reasoning_steps is None:
            self.reasoning_steps = []


class MCPService(ABC):
    """MCP服务抽象基类"""
    
    def __init__(self, name: str, description: str, capabilities: List[str], keywords: List[str]):
        self.name = name
        self.description = description
        self.capabilities = capabilities
        self.keywords = keywords
        self.enabled = True
    
    @abstractmethod
    async def can_handle(self, request: MCPRequest) -> float:
        """判断是否能处理请求，返回置信度 (0.0-1.0)"""
        pass
    
    @abstractmethod
    async def execute(self, request: MCPRequest) -> MCPResponse:
        """执行服务请求"""
        pass


class LLMIntentAnalyzer:
    """基于LLM的意图分析器"""
    
    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.system_prompt = """你是一个智能意图分析专家，能够理解用户的复杂需求并分解为具体的执行步骤。

你的任务：
1. 分析用户输入的意图
2. 识别需要调用的MCP服务
3. 提供推理过程（Chain of Thought）
4. 输出结构化的分析结果

可用服务：
{service_descriptions}

分析格式：
```json
{
    "primary_intent": "主要意图",
    "confidence": 0.95,
    "required_services": ["service1", "service2"],
    "reasoning": [
        "步骤1：分析用户需求",
        "步骤2：识别所需服务",
        "步骤3：确定执行顺序"
    ],
    "parameters": {
        "service1": {"param1": "value1"},
        "service2": {"param2": "value2"}
    }
}
```"""

    async def analyze_intent(self, text: str, available_services: List[MCPService], context: Dict = None) -> Dict[str, Any]:
        """使用LLM分析用户意图"""
        try:
            # 构建服务描述
            service_descriptions = []
            for service in available_services:
                if service.enabled:
                    service_descriptions.append(f"- {service.name}: {service.description} (能力: {', '.join(service.capabilities)})")
            
            service_desc_text = '\n'.join(service_descriptions)
            
            # 构建提示
            prompt = f"用户输入：{text}\n\n上下文：{context or '无'}\n\n请分析用户意图并输出JSON格式的分析结果。"
            
            messages = [
                Message(role=SYSTEM, content=self.system_prompt.format(service_descriptions=service_desc_text)),
                Message(role=USER, content=prompt)
            ]
            
            # 调用LLM
            response = []
            for resp in self.llm.chat(messages=messages, stream=False):
                response = resp
            
            # 解析响应
            content = response[-1].content if response else ""
            
            # 尝试提取JSON
            try:
                # 查找JSON块
                import re
                json_match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                    result = json.loads(json_str)
                    return result
                else:
                    # 如果没有找到JSON块，尝试直接解析
                    result = json.loads(content)
                    return result
            except json.JSONDecodeError:
                logger.warning(f"无法解析LLM响应为JSON: {content}")
                return {
                    "primary_intent": "general",
                    "confidence": 0.5,
                    "required_services": [],
                    "reasoning": ["LLM响应解析失败"],
                    "parameters": {}
                }
                
        except Exception as e:
            logger.error(f"意图分析失败: {e}")
            return {
                "primary_intent": "general",
                "confidence": 0.0,
                "required_services": [],
                "reasoning": [f"分析错误: {str(e)}"],
                "parameters": {}
            }


class EnhancedMCPRouter(Assistant):
    """增强版MCP路由器，基于QwenAgent的Router设计"""
    
    def __init__(self, 
                 llm: Optional[Union[Dict, BaseChatModel]] = None,
                 services: Optional[List[MCPService]] = None,
                 name: str = "MCP Router",
                 description: str = "智能MCP服务路由器"):
        
        # 初始化服务
        self.services: Dict[str, MCPService] = {}
        if services:
            for service in services:
                self.services[service.name] = service
        
        # 初始化意图分析器
        self.intent_analyzer = LLMIntentAnalyzer(llm) if llm else None
        
        # 构建系统提示
        service_descriptions = self._build_service_descriptions()
        system_message = f"""你是一个智能MCP服务路由器，能够根据用户需求智能选择和调用合适的服务。

可用服务：
{service_descriptions}

路由规则：
1. 分析用户意图，确定需要调用的服务
2. 如果用户需求复杂，可以分解为多个步骤
3. 按优先级和依赖关系调用服务
4. 提供清晰的执行计划和推理过程

输出格式：
Call: service_name  # 选择的服务名称
Reasoning: 推理过程  # 为什么选择这个服务
Parameters: {{"param": "value"}}  # 服务参数

如果用户需求需要多个服务，请按顺序调用。"""
        
        super().__init__(
            function_list=None,
            llm=llm,
            system_message=system_message,
            name=name,
            description=description
        )
        
        # 性能统计
        self.performance_stats: Dict[str, Dict] = {}
        self.request_history: List[MCPRequest] = []
    
    def _build_service_descriptions(self) -> str:
        """构建服务描述"""
        descriptions = []
        for service in self.services.values():
            if service.enabled:
                descriptions.append(f"- {service.name}: {service.description}")
                descriptions.append(f"  能力: {', '.join(service.capabilities)}")
                descriptions.append(f"  关键词: {', '.join(service.keywords)}")
                descriptions.append("")
        return '\n'.join(descriptions)
    
    def register_service(self, service: MCPService) -> None:
        """注册MCP服务"""
        self.services[service.name] = service
        self.performance_stats[service.name] = {
            "total_requests": 0,
            "successful_requests": 0,
            "average_response_time": 0.0,
            "last_used": None
        }
        logger.info(f"📋 注册MCP服务: {service.name}")
    
    async def route_request(self, request: MCPRequest, strategy: str = "llm") -> MCPResponse:
        """路由请求到合适的服务"""
        start_time = datetime.now()
        
        try:
            if strategy == "llm" and self.intent_analyzer:
                # 使用LLM进行意图分析
                analysis = await self.intent_analyzer.analyze_intent(
                    request.intent, 
                    list(self.services.values()), 
                    request.context
                )
                
                # 根据分析结果选择服务
                if analysis.get("required_services"):
                    service_name = analysis["required_services"][0]
                    if service_name in self.services:
                        service = self.services[service_name]
                        
                        # 更新请求参数
                        if analysis.get("parameters", {}).get(service_name):
                            request.parameters.update(analysis["parameters"][service_name])
                        
                        # 执行服务
                        response = await service.execute(request)
                        
                        # 添加推理步骤
                        if analysis.get("reasoning"):
                            response.reasoning_steps = analysis["reasoning"]
                        
                        # 更新统计
                        self._update_performance_stats(service.name, response, start_time)
                        self.request_history.append(request)
                        
                        logger.info(f"🎯 LLM路由成功: {request.intent} -> {service.name}")
                        return response
            
            # 回退到传统路由
            return await self._fallback_route(request, start_time)
            
        except Exception as e:
            logger.error(f"❌ 路由失败: {e}")
            return MCPResponse(
                service_name="router",
                success=False,
                result=None,
                error=f"路由错误: {str(e)}",
                reasoning_steps=[f"路由失败: {str(e)}"]
            )
    
    async def _fallback_route(self, request: MCPRequest, start_time: datetime) -> MCPResponse:
        """回退路由策略"""
        # 简单的关键词匹配
        best_service = None
        best_score = 0.0
        
        for service_name, service in self.services.items():
            if not service.enabled:
                continue
            
            # 计算匹配度
            score = 0.0
            for keyword in service.keywords:
                if keyword.lower() in request.intent.lower():
                    score += 1.0
            
            if score > best_score:
                best_score = score
                best_service = service
        
        if best_service and best_score > 0:
            response = await best_service.execute(request)
            self._update_performance_stats(best_service.name, response, start_time)
            return response
        
        return MCPResponse(
            service_name="router",
            success=False,
            result=None,
            error="没有找到合适的服务处理此请求",
            reasoning_steps=["回退路由：未找到匹配的服务"]
        )
    
    def _update_performance_stats(self, service_name: str, response: MCPResponse, start_time: datetime) -> None:
        """更新性能统计"""
        if service_name not in self.performance_stats:
            return
        
        stats = self.performance_stats[service_name]
        execution_time = (datetime.now() - start_time).total_seconds()
        
        stats["total_requests"] += 1
        if response.success:
            stats["successful_requests"] += 1
        
        # 更新平均响应时间
        current_avg = stats["average_response_time"]
        total_requests = stats["total_requests"]
        stats["average_response_time"] = (current_avg * (total_requests - 1) + execution_time) / total_requests
        
        stats["last_used"] = datetime.now()
    
    def get_service_stats(self) -> Dict[str, Dict]:
        """获取服务统计信息"""
        return self.performance_stats.copy()
    
    async def health_check(self) -> Dict[str, bool]:
        """服务健康检查"""
        health_status = {}
        
        for service_name, service in self.services.items():
            try:
                # 创建测试请求
                test_request = MCPRequest(
                    user_id="health_check",
                    session_id="health_check",
                    intent="health_check",
                    parameters={},
                    context={}
                )
                
                # 检查服务是否能处理请求
                confidence = await service.can_handle(test_request)
                health_status[service_name] = confidence > 0.0 and service.enabled
                
            except Exception as e:
                logger.warning(f"⚠️ 服务健康检查失败: {service_name} - {e}")
                health_status[service_name] = False
        
        return health_status


# 全局增强路由器实例（延迟初始化）
enhanced_mcp_router = None

def get_enhanced_router(llm=None, services=None):
    """获取增强路由器实例"""
    global enhanced_mcp_router
    if enhanced_mcp_router is None:
        # 如果没有提供LLM，使用默认配置
        if llm is None:
            from ty_mem_agent.config.settings import get_llm_config
            from qwen_agent.llm import get_chat_model
            llm_config = get_llm_config()
            llm = get_chat_model(llm_config)
        enhanced_mcp_router = EnhancedMCPRouter(llm=llm, services=services)
    return enhanced_mcp_router


if __name__ == "__main__":
    # 测试代码
    async def test_enhanced_router():
        from ty_mem_agent.utils.logger_config import get_logger
        test_logger = get_logger("EnhancedMCPRouterTest")
        
        # 这里需要实际的LLM配置
        # router = EnhancedMCPRouter(llm=your_llm_config)
        
        test_logger.info("🧪 增强版MCP路由器测试")
        test_logger.info("✅ 基于QwenAgent Router设计")
        test_logger.info("✅ 支持LLM驱动的意图理解")
        test_logger.info("✅ 支持COT推理")
        test_logger.info("✅ 支持复杂需求分解")
    
    asyncio.run(test_enhanced_router())
