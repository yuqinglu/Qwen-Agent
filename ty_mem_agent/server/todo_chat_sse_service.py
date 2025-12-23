#!/usr/bin/env python3
"""
待办聊天SSE流式服务
实现基于ReAct的AI对话，并通过SSE流式返回处理过程
"""

import json
import uuid
import asyncio
from datetime import datetime
from typing import AsyncIterator, Dict, List, Optional, Any
from loguru import logger

from .todo_chat_manager import get_todo_chat_manager, TodoChatSession


class ExecutionStep:
    """执行步骤"""
    def __init__(self, step_id: int, step_type: str, desc: str):
        self.id = step_id
        self.type = step_type  # analysis, tool, update, generate
        self.desc = desc
        self.status = "pending"  # pending, running, completed, failed
        self.progress = 0.0
        self.error = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "type": self.type,
            "desc": self.desc,
            "status": self.status,
            "progress": self.progress,
            "error": self.error
        }
    
    def update_status(self, status: str, desc: Optional[str] = None, progress: Optional[float] = None):
        """更新步骤状态"""
        self.status = status
        if desc:
            self.desc = desc
        if progress is not None:
            self.progress = progress


class TodoChatSSEService:
    """待办聊天SSE流式服务"""
    
    def __init__(self):
        self.chat_manager = get_todo_chat_manager()
    
    async def process_message_stream(
        self,
        event_id: int,
        user_id: int,
        content: str,
        session_id: Optional[str] = None,
        title: Optional[str] = None,
        todo_content: Optional[str] = None,
        rich_cards: Optional[List[Dict]] = None
    ) -> AsyncIterator[str]:
        """
        处理用户消息并流式返回结果
        
        Args:
            event_id: 待办事件ID
            user_id: 用户ID
            content: 用户消息内容
            session_id: 会话ID（为空则创建新会话）
            title: 会话标题（仅创建新会话时有效）
            todo_content: 当前待办内容
            rich_cards: 当前富媒体卡片列表
            
        Yields:
            SSE格式的事件流
        """
        start_time = datetime.now()
        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        full_message_content = ""  # 完整的AI回复内容
        new_todo_content = None
        new_rich_cards = []
        suggestions = []
        
        try:
            # ========== 阶段 1: 会话初始化 ==========
            session = await self._init_session(
                event_id, user_id, session_id, title, 
                todo_content, rich_cards
            )
            
            # 推送会话初始化事件
            yield self._format_sse_event("session_init", {
                "session_id": session.session_id,
                "event_id": event_id,
                "created_at": session.created_at,
                "is_new": session_id is None
            })
            
            # 保存用户消息
            self.chat_manager.add_message(
                session.session_id,
                role="user",
                content=content
            )
            
            # ========== 阶段 2: 生成执行计划 ==========
            steps = self._create_execution_plan(content)
            yield self._format_sse_event("plan_update", {
                "steps": [step.to_dict() for step in steps]
            })
            
            await asyncio.sleep(0.1)  # 模拟思考时间
            
            # ========== 阶段 3: 分析用户意图 ==========
            analysis_step = steps[0]
            analysis_step.update_status("running")
            yield self._format_sse_event("plan_update", {
                "steps": [step.to_dict() for step in steps]
            })
            
            # TODO: 调用AI分析用户意图
            await asyncio.sleep(0.5)
            analysis_result = await self._analyze_intent(
                content, todo_content, session.messages
            )
            
            analysis_step.update_status(
                "completed", 
                desc=f"分析用户意图：{analysis_result.get('summary', '已完成')}"
            )
            yield self._format_sse_event("plan_update", {
                "steps": [step.to_dict() for step in steps]
            })
            
            # ========== 阶段 4: 调用工具/MCP ==========
            if analysis_result.get("need_tools"):
                tool_step = steps[1]
                tool_step.update_status("running", desc="正在调用相关服务...")
                yield self._format_sse_event("plan_update", {
                    "steps": [step.to_dict() for step in steps]
                })
                
                # 调用工具
                tool_results = await self._call_tools(analysis_result.get("tools", []))
                
                # 推送富媒体卡片
                for card in tool_results.get("rich_cards", []):
                    new_rich_cards.append(card)
                    yield self._format_sse_event("rich_card", card)
                    await asyncio.sleep(0.1)
                
                tool_step.update_status("completed", desc="服务调用完成")
                yield self._format_sse_event("plan_update", {
                    "steps": [step.to_dict() for step in steps]
                })
            
            # ========== 阶段 5: 更新待办内容 ==========
            if analysis_result.get("need_update_todo"):
                update_step = steps[2]
                update_step.update_status("running", desc="正在生成新的待办内容...")
                yield self._format_sse_event("plan_update", {
                    "steps": [step.to_dict() for step in steps]
                })
                
                # 生成新的待办内容
                new_todo_content = await self._generate_todo_content(
                    content, todo_content, analysis_result
                )
                
                # 推送待办更新
                yield self._format_sse_event("todo_update", {
                    "base_version": 1,
                    "new_version": 2,
                    "change_summary": analysis_result.get("change_summary", "已更新待办内容"),
                    "new_content": new_todo_content
                })
                
                update_step.update_status("completed", desc="待办内容已更新")
                yield self._format_sse_event("plan_update", {
                    "steps": [step.to_dict() for step in steps]
                })
            
            # ========== 阶段 6: 生成AI回复（流式） ==========
            generate_step = steps[3]
            generate_step.update_status("running", desc="正在生成回复...")
            yield self._format_sse_event("plan_update", {
                "steps": [step.to_dict() for step in steps]
            })
            
            # 流式生成回复内容
            async for delta in self._generate_response_stream(
                content, todo_content, new_todo_content, 
                analysis_result, new_rich_cards
            ):
                full_message_content += delta
                yield self._format_sse_event("message_delta", {"content": delta})
                await asyncio.sleep(0.05)  # 控制推送频率
            
            generate_step.update_status("completed", desc="回复生成完成")
            yield self._format_sse_event("plan_update", {
                "steps": [step.to_dict() for step in steps]
            })
            
            # ========== 阶段 7: 生成建议待办 ==========
            if analysis_result.get("need_suggestions"):
                suggestions = await self._generate_suggestions(
                    event_id, content, todo_content, analysis_result
                )
                
                if suggestions:
                    yield self._format_sse_event("suggestions", suggestions)
            
            # ========== 阶段 8: 保存并完成 ==========
            # 保存AI回复消息
            self.chat_manager.add_message(
                session.session_id,
                role="assistant",
                content=full_message_content,
                todo_content=new_todo_content,
                suggested_todos=suggestions,
                rich_cards=new_rich_cards
            )
            
            # 更新会话上下文
            if new_todo_content:
                self.chat_manager.update_session_context(
                    session.session_id,
                    todo_content=new_todo_content,
                    rich_cards=new_rich_cards
                )
            
            # 推送完成事件
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            yield self._format_sse_event("done", {
                "message_id": message_id,
                "session_id": session.session_id,
                "usage": {
                    "input_tokens": 150,  # TODO: 从AI获取真实token使用量
                    "output_tokens": 280,
                    "total_tokens": 430
                },
                "duration_ms": duration_ms
            })
            
            logger.info(f"✅ 待办聊天处理完成: session={session.session_id}, duration={duration_ms}ms")
            
        except Exception as e:
            logger.error(f"❌ 待办聊天处理失败: {e}", exc_info=True)
            yield self._format_sse_event("error", {
                "code": 500,
                "message": "处理失败",
                "detail": str(e),
                "recoverable": True
            })
            yield self._format_sse_event("done", {
                "message_id": None,
                "error": True
            })
    
    async def _init_session(
        self,
        event_id: int,
        user_id: int,
        session_id: Optional[str],
        title: Optional[str],
        todo_content: Optional[str],
        rich_cards: Optional[List[Dict]]
    ) -> TodoChatSession:
        """初始化或获取会话"""
        if session_id:
            session = self.chat_manager.get_session(session_id)
            if session:
                return session
            else:
                logger.warning(f"⚠️ 会话不存在，创建新会话: {session_id}")
        
        # 创建新会话
        return self.chat_manager.create_session(
            event_id=event_id,
            user_id=user_id,
            title=title or "新对话",
            todo_content=todo_content,
            rich_cards=rich_cards
        )
    
    def _create_execution_plan(self, content: str) -> List[ExecutionStep]:
        """创建执行计划"""
        return [
            ExecutionStep(1, "analysis", "分析用户意图"),
            ExecutionStep(2, "tool", "查询相关服务"),
            ExecutionStep(3, "update", "更新待办内容"),
            ExecutionStep(4, "generate", "生成回复")
        ]
    
    async def _analyze_intent(
        self,
        content: str,
        todo_content: Optional[str],
        history_messages: List
    ) -> Dict[str, Any]:
        """分析用户意图"""
        # TODO: 调用AI模型分析用户意图
        # 这里暂时返回模拟数据
        
        # 简单关键词匹配
        need_tools = any(keyword in content for keyword in ["天气", "导航", "打车", "酒店", "机票"])
        need_update_todo = any(keyword in content for keyword in ["补充", "完善", "修改", "添加", "更新"])
        need_suggestions = any(keyword in content for keyword in ["建议", "推荐", "准备", "计划"])
        
        return {
            "summary": "识别用户需求并制定执行计划",
            "need_tools": need_tools,
            "tools": ["weather"] if "天气" in content else [],
            "need_update_todo": need_update_todo,
            "need_suggestions": need_suggestions,
            "change_summary": "添加详细信息" if need_update_todo else None
        }
    
    async def _call_tools(self, tools: List[str]) -> Dict[str, Any]:
        """调用工具/MCP"""
        # TODO: 调用实际的MCP工具
        # 这里返回模拟数据
        await asyncio.sleep(0.5)
        
        rich_cards = []
        if "weather" in tools:
            rich_cards.append({
                "card_id": f"card_weather_{uuid.uuid4().hex[:6]}",
                "card_type": "weather",
                "title": "明天天气",
                "subtitle": "北京市海淀区",
                "icon": "weather_sunny",
                "data": {
                    "city": "北京",
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "weather": "晴",
                    "temperature_high": 22,
                    "temperature_low": 15,
                    "humidity": 45,
                    "wind": "东北风3级",
                    "air_quality": "良",
                    "suggestion": "天气晴好，适合户外活动"
                },
                "source": "高德天气",
                "updated_at": datetime.now().isoformat()
            })
        
        return {"rich_cards": rich_cards}
    
    async def _generate_todo_content(
        self,
        content: str,
        old_content: Optional[str],
        analysis_result: Dict
    ) -> str:
        """生成新的待办内容"""
        # TODO: 调用AI模型生成新的待办内容
        # 这里返回模拟数据
        await asyncio.sleep(0.5)
        
        if not old_content:
            return "## 新的待办\n\n根据您的需求生成的内容"
        
        # 简单地在原内容后追加
        return old_content + "\n\n### 补充内容\n根据您的需求添加的详细信息"
    
    async def _generate_response_stream(
        self,
        content: str,
        old_todo: Optional[str],
        new_todo: Optional[str],
        analysis_result: Dict,
        rich_cards: List[Dict]
    ) -> AsyncIterator[str]:
        """流式生成AI回复"""
        # TODO: 调用AI模型流式生成回复
        # 这里返回模拟数据
        
        response = "好的，我已经为您处理完成。"
        
        if new_todo:
            response = "我已经根据您的需求更新了待办内容。"
        
        if rich_cards:
            response += f"同时为您查询了相关信息。"
        
        # 模拟流式输出
        for char in response:
            yield char
            await asyncio.sleep(0.02)
    
    async def _generate_suggestions(
        self,
        event_id: int,
        content: str,
        todo_content: Optional[str],
        analysis_result: Dict
    ) -> List[Dict]:
        """生成建议待办"""
        # TODO: 调用AI模型生成建议待办
        # 这里返回模拟数据
        await asyncio.sleep(0.3)
        
        if not analysis_result.get("need_suggestions"):
            return []
        
        return [
            {
                "suggested_todo_id": f"sug_{uuid.uuid4().hex[:8]}",
                "title": "准备相关材料",
                "description": "根据当前待办建议准备的材料",
                "event_date_time": datetime.now().isoformat(),
                "duration": 3600,
                "priority": 2,
                "relation_type": "prerequisite",
                "relation_event_id": event_id,
                "todo_content": "## 材料准备\n- [ ] 相关文档\n- [ ] 数据报告",
                "status": "suggested"
            }
        ]
    
    def _format_sse_event(self, event_type: str, data: Any) -> str:
        """格式化SSE事件"""
        json_data = json.dumps(data, ensure_ascii=False)
        return f"event: {event_type}\ndata: {json_data}\n\n"


# 全局实例
_sse_service = None


def get_todo_chat_sse_service() -> TodoChatSSEService:
    """获取待办聊天SSE服务实例"""
    global _sse_service
    if _sse_service is None:
        _sse_service = TodoChatSSEService()
    return _sse_service



