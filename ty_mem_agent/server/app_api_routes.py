#!/usr/bin/env python3
"""
APP API 路由
为APP端提供的API接口，包括一句话创建待办、待办AI聊天等功能

⚠️ 重要说明：用户标识方式
- 所有APP API接口使用 X-USER-ID Header 标识用户
- X-USER-ID 是整数类型（Integer），对应 calendar_user_id
- 不要使用字符串类型的 user_id（如 "user_xxx"）
- 在测试页面中，应该使用从 /user/calendar-id 接口获取的 calendar_user_id 作为 X-USER-ID
"""

import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Header, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from loguru import logger

from ty_mem_agent.server.user_manager import user_manager
from ty_mem_agent.server.user_id_mapper import UserIdMapper
from ty_mem_agent.self_defined_tools.todo_tools import TodoExtractorTool
from ty_mem_agent.mcp_integrations.calendar_mcp_server import CalendarEventManager
from ty_mem_agent.server.todo_chat_manager import get_todo_chat_manager
from ty_mem_agent.server.rich_card_manager import get_rich_card_manager, CARD_TYPES
from ty_mem_agent.agents.todo_chat_agent import get_todo_chat_agent
from ty_mem_agent.server.todo_chat_sse_service import get_todo_chat_sse_service


# ==================== Pydantic 模型 ====================

class QuickCreateTodoRequest(BaseModel):
    """一句话创建待办请求"""
    text: str = Field(..., description="用户的自然语言描述")
    timezone: str = Field(default="Asia/Shanghai", description="时区")


class QuickCreateTodoResponse(BaseModel):
    """一句话创建待办响应"""
    code: int = Field(default=0, description="响应码")
    message: str = Field(default="success", description="响应消息")
    data: Optional[Dict[str, Any]] = Field(default=None, description="响应数据")


class AIUnderstanding(BaseModel):
    """AI对用户意图的理解"""
    extracted_time: Optional[str] = None
    extracted_action: Optional[str] = None
    extracted_participants: Optional[List[str]] = None
    extracted_topic: Optional[str] = None
    confidence: float = 0.0


# ==================== API 路由 ====================

# 创建路由器
router = APIRouter(prefix="/api/v1", tags=["APP API"])


def get_user_by_header(x_user_id: int = Header(..., alias="x-user-id", description="用户ID（整数类型，对应calendar_user_id）")) -> Dict[str, Any]:
    """
    通过X-USER-ID头获取用户信息（如果用户不存在则自动创建）
    
    ⚠️ 重要说明：
    - X-USER-ID 是整数类型（Integer），对应 calendar_user_id
    - 不要使用字符串类型的 user_id（如 "user_xxx"）
    - 如果用户不存在，会自动创建用户（用于APP API调用）
    - 在测试页面中，应该使用从 /user/calendar-id 接口获取的 calendar_user_id 作为 X-USER-ID
    
    Args:
        x_user_id: calendar_user_id（整数类型），对应日历MCP服务中的用户ID
        
    Returns:
        用户信息字典，包含user_id和calendar_user_id
        
    Raises:
        HTTPException: 如果自动创建用户失败
    """
    # X-USER-ID 是整数类型，直接作为 calendar_user_id 使用
    # 注意：不要使用字符串类型的 user_id（如 "user_xxx"）
    
    # 尝试获取用户，如果不存在则自动创建
    user = user_manager.get_or_create_user_by_calendar_id(x_user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"无法创建或获取用户: calendar_user_id={x_user_id}"
        )
    
    # 确保calendar_user_id已设置
    if not user.calendar_user_id:
        calendar_user_id = UserIdMapper.get_calendar_user_id(user.user_id)
        # 更新用户信息
        user_manager.db.update_user(user.user_id, {
            'calendar_user_id': calendar_user_id
        })
        user.calendar_user_id = calendar_user_id
    else:
        calendar_user_id = user.calendar_user_id
    
    return {
        "user_id": user.user_id,
        "x_user_id": x_user_id,
        "calendar_user_id": calendar_user_id,
        "user": user
    }


@router.post("/todo/quick-create", response_model=QuickCreateTodoResponse)
async def quick_create_todo(
    request: QuickCreateTodoRequest,
    x_user_id: int = Header(..., alias="x-user-id", description="用户ID（整数类型，对应calendar_user_id）")
):
    """
    一句话创建待办
    
    用户通过一句自然语言描述，AI自动解析并创建待办事项
    
    ⚠️ 重要：X-USER-ID 是整数类型，对应 calendar_user_id，不要使用字符串类型的 user_id
    
    - **text**: 用户的自然语言描述，如"明天下午三点开会"
    - **timezone**: 时区，默认 "Asia/Shanghai"
    """
    logger.info(f"📝 一句话创建待办请求: user_id={x_user_id}, text={request.text[:50]}...")
    
    try:
        # 获取用户信息
        user_info = get_user_by_header(x_user_id)
        user_id = user_info["user_id"]
        calendar_user_id = user_info["calendar_user_id"]
        
        logger.info(f"📝 用户信息: user_id={user_id}, calendar_user_id={calendar_user_id}")
        
        # 使用TodoExtractorTool提取待办信息
        extractor = TodoExtractorTool()
        extract_result_str = extractor.call({
            "text": request.text,
            "user_id": user_id
        })
        
        extract_result = json.loads(extract_result_str)
        
        if not extract_result.get("success"):
            logger.error(f"❌ 提取待办信息失败: {extract_result.get('error')}")
            return QuickCreateTodoResponse(
                code=1001,
                message=f"解析失败: {extract_result.get('error', '未知错误')}",
                data=None
            )
        
        # 获取提取的信息
        extracted_info = extract_result.get("extracted_info", {})
        calendar_event_params = extract_result.get("calendar_event_params", {})
        is_recurring = extract_result.get("is_recurring", False)
        
        logger.info(f"📝 提取的待办信息: {json.dumps(extracted_info, ensure_ascii=False)[:200]}...")
        logger.info(f"📝 日历事件参数: {json.dumps(calendar_event_params, ensure_ascii=False)[:200]}...")
        
        # 使用CalendarEventManager创建待办
        calendar_manager = CalendarEventManager(user_id=calendar_user_id)
        
        if is_recurring:
            # 创建重复事件
            result_str = calendar_manager.create_recurring_event(
                title=calendar_event_params.get("title", "未命名待办"),
                rrule=calendar_event_params.get("rrule", ""),
                duration=calendar_event_params.get("duration", 3600),
                event_date_time=calendar_event_params.get("eventDateTime"),
                description=calendar_event_params.get("description"),
                location=calendar_event_params.get("location"),
                timezone=request.timezone
            )
        else:
            # 创建一次性事件
            result_str = calendar_manager.create_one_time_event(
                title=calendar_event_params.get("title", "未命名待办"),
                duration=calendar_event_params.get("duration", 3600),
                description=calendar_event_params.get("description"),
                location=calendar_event_params.get("location"),
                timezone=request.timezone,
                event_date_time=calendar_event_params.get("eventDateTime")
            )
        
        logger.info(f"📝 日历MCP返回结果: {result_str[:200] if isinstance(result_str, str) else str(result_str)[:200]}...")
        
        # 解析MCP返回结果
        try:
            if isinstance(result_str, str):
                mcp_result = json.loads(result_str)
            else:
                mcp_result = result_str
        except json.JSONDecodeError:
            logger.warning(f"⚠️ MCP返回结果不是有效的JSON: {result_str[:200]}")
            mcp_result = {}
        
        # 从MCP返回结果中提取 event_id
        # MCP返回格式: {"event": {"id": 28, ...}}
        event_id = None
        if isinstance(mcp_result, dict) and "event" in mcp_result:
            event_obj = mcp_result.get("event", {})
            if isinstance(event_obj, dict):
                event_id = event_obj.get("id")
        
        # 构建AI理解信息
        ai_understanding = {
            "extracted_time": extracted_info.get("start_time") or extracted_info.get("deadline"),
            "extracted_action": extracted_info.get("title"),
            "extracted_participants": extracted_info.get("participants", []),
            "extracted_topic": extracted_info.get("description"),
            "confidence": 0.92  # 可以根据实际情况调整
        }
        
        # 构建响应数据
        response_data = {
            "event_id": event_id,
            "title": calendar_event_params.get("title"),
            "event_date_time": calendar_event_params.get("eventDateTime"),
            "duration": calendar_event_params.get("duration", 3600),
            "description": calendar_event_params.get("description"),
            "location": calendar_event_params.get("location"),
            "is_recurring": is_recurring,
            "rrule": calendar_event_params.get("rrule") if is_recurring else None,
            "ai_understanding": ai_understanding
        }
        
        logger.info(f"✅ 待办创建成功: event_id={response_data.get('event_id')}, title={response_data.get('title')}")
        
        return QuickCreateTodoResponse(
            code=0,
            message="success",
            data=response_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 创建待办失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return QuickCreateTodoResponse(
            code=500,
            message=f"服务器错误: {str(e)}",
            data=None
        )


class ExtractTodoParamsRequest(BaseModel):
    """提取待办参数请求"""
    text: str = Field(..., description="用户的自然语言描述")
    timezone: str = Field(default="Asia/Shanghai", description="时区")


class ExtractTodoParamsResponse(BaseModel):
    """提取待办参数响应"""
    code: int = Field(default=0, description="响应码")
    message: str = Field(default="success", description="响应消息")
    data: Optional[Dict[str, Any]] = Field(default=None, description="响应数据")


@router.post("/todo/extract-params", response_model=ExtractTodoParamsResponse)
async def extract_todo_params(
    request: ExtractTodoParamsRequest,
    x_user_id: int = Header(..., alias="x-user-id", description="用户ID（整数类型，对应calendar_user_id）")
):
    """
    提取待办核心参数（不创建待办）
    
    从用户的自然语言描述中提取待办事项的核心参数，但不调用日历MCP创建待办。
    只返回提取的参数，供客户端使用。
    
    ⚠️ 重要：X-USER-ID 是整数类型，对应 calendar_user_id，不要使用字符串类型的 user_id
    
    参数说明：
    - **text**: 用户的自然语言描述，如"明天下午三点开会"
    - **timezone**: 时区，默认 "Asia/Shanghai"
    
    返回参数包括：
    - title: 待办标题
    - date: 事件日期，格式为 YYYYmmdd（如 20231225）
    - time: 事件时间，格式为 HHmmss（如 143000）
    - duration: 持续时间（秒）
    - description: 描述
    - location: 地点
    - participants: 参与者列表
    - is_recurring: 是否为重复事件
    - recurrenceRule: 重复规则，参考 iCalendar RFC 5545（如果是重复事件）
    - alarmTrigger: 提醒触发器，提前多少时间提醒，参考 iCalendar RFC 5545
    - timezone: 时区
    """
    logger.info(f"📝 提取待办参数请求: user_id={x_user_id}, text={request.text[:50]}...")
    
    try:
        # 获取用户信息
        user_info = get_user_by_header(x_user_id)
        user_id = user_info["user_id"]
        calendar_user_id = user_info["calendar_user_id"]
        
        logger.info(f"📝 用户信息: user_id={user_id}, calendar_user_id={calendar_user_id}")
        
        # 使用TodoExtractorTool提取待办信息
        extractor = TodoExtractorTool()
        extract_result_str = extractor.call({
            "text": request.text,
            "user_id": user_id
        })
        
        extract_result = json.loads(extract_result_str)
        
        if not extract_result.get("success"):
            logger.error(f"❌ 提取待办信息失败: {extract_result.get('error')}")
            return ExtractTodoParamsResponse(
                code=1001,
                message=f"解析失败: {extract_result.get('error', '未知错误')}",
                data=None
            )
        
        # 获取提取的信息
        extracted_info = extract_result.get("extracted_info", {})
        calendar_event_params = extract_result.get("calendar_event_params", {})
        is_recurring = extract_result.get("is_recurring", False)
        
        logger.info(f"📝 提取的待办信息: {json.dumps(extracted_info, ensure_ascii=False)[:200]}...")
        logger.info(f"📝 日历事件参数: {json.dumps(calendar_event_params, ensure_ascii=False)[:200]}...")
        
        # 处理日期时间，将 event_date_time 拆分为 date 和 time
        event_date_time = calendar_event_params.get("eventDateTime")
        date_str = None
        time_str = None
        
        if event_date_time:
            try:
                # 解析 RFC3339 格式的时间
                from datetime import datetime
                dt = datetime.fromisoformat(event_date_time.replace('Z', '+00:00'))
                # 转换为 YYYYmmdd 和 HHmmss 格式
                date_str = dt.strftime("%Y%m%d")
                time_str = dt.strftime("%H%M%S")
            except Exception as e:
                logger.warning(f"⚠️ 解析日期时间失败: {e}, event_date_time={event_date_time}")
        
        # 获取提醒触发器（alarmTrigger）
        # 从 calendar_event_params 中获取，如果没有提到提醒则为 None
        alarm_trigger = calendar_event_params.get("alarm_trigger")
        
        # 构建响应数据
        response_data = {
            "title": calendar_event_params.get("title"),
            "date": date_str,
            "time": time_str,
            "duration": calendar_event_params.get("duration", 3600),
            "description": calendar_event_params.get("description"),
            "location": calendar_event_params.get("location"),
            "participants": extracted_info.get("participants", []),
            "is_recurring": is_recurring,
            "recurrenceRule": calendar_event_params.get("rrule") if is_recurring else None,
            "alarmTrigger": alarm_trigger,  # 从提取结果中获取，如果用户没有提到提醒则为 None
            "timezone": request.timezone
        }
        
        logger.info(f"✅ 待办参数提取成功: title={response_data.get('title')}, date={date_str}, time={time_str}, is_recurring={is_recurring}")
        
        return ExtractTodoParamsResponse(
            code=0,
            message="success",
            data=response_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 提取待办参数失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return ExtractTodoParamsResponse(
            code=500,
            message=f"服务器错误: {str(e)}",
            data=None
        )


@router.get("/todo/list")
async def list_todos(
    x_user_id: int = Header(..., alias="x-user-id", description="用户ID（整数类型，对应calendar_user_id）"),
    range_start: Optional[str] = None,
    range_end: Optional[str] = None,
    timezone: str = "Asia/Shanghai"
):
    """
    查询待办列表
    
    ⚠️ 重要：X-USER-ID 是整数类型，对应 calendar_user_id，不要使用字符串类型的 user_id
    
    - **range_start**: 查询开始时间（RFC3339格式）
    - **range_end**: 查询结束时间（RFC3339格式）
    - **timezone**: 时区，默认 "Asia/Shanghai"
    """
    logger.info(f"📋 查询待办列表: user_id={x_user_id}")
    
    try:
        # 获取用户信息
        user_info = get_user_by_header(x_user_id)
        calendar_user_id = user_info["calendar_user_id"]
        
        # 使用CalendarEventManager查询待办
        calendar_manager = CalendarEventManager(user_id=calendar_user_id)
        result_str = calendar_manager.query_events(
            timezone=timezone,
            range_start=range_start,
            range_end=range_end
        )
        
        # 解析结果
        try:
            if isinstance(result_str, str):
                result = json.loads(result_str)
            else:
                result = result_str
        except json.JSONDecodeError:
            result = {"raw_result": result_str}
        
        # 提取事件列表
        events = []
        if isinstance(result, dict):
            events = result.get("eventInstanceList", result.get("instances", result.get("events", [])))
        elif isinstance(result, list):
            events = result
        
        return {
            "code": 0,
            "message": "success",
            "data": {
                "total": len(events),
                "events": events
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 查询待办失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "code": 500,
            "message": f"服务器错误: {str(e)}",
            "data": None
        }


# ==================== 待办聊天会话接口 ====================

class CreateTodoChatSessionRequest(BaseModel):
    """创建待办聊天会话请求"""
    content: str = Field(..., description="初始用户消息（必选）")
    title: Optional[str] = Field(default=None, description="会话标题（可选，如不提供则自动生成）")
    todo_content: Optional[str] = Field(default=None, description="当前待办的正文内容（Markdown格式）")
    rich_cards: Optional[List[Dict[str, Any]]] = Field(default=None, description="当前待办关联的富媒体卡片列表")


class TodoChatReply(BaseModel):
    """AI回复"""
    message_id: str
    content: str
    todo_content: Optional[str] = None
    suggested_todos: List[Dict[str, Any]] = []
    rich_cards: List[Dict[str, Any]] = []


class CreateTodoChatSessionResponse(BaseModel):
    """创建待办聊天会话响应"""
    code: int = Field(default=0, description="响应码")
    message: str = Field(default="success", description="响应消息")
    data: Optional[Dict[str, Any]] = Field(default=None, description="响应数据")


@router.post("/todo/{event_id}/chat/sessions", response_model=CreateTodoChatSessionResponse)
async def create_todo_chat_session(
    event_id: int,
    request: CreateTodoChatSessionRequest,
    x_user_id: int = Header(..., alias="x-user-id", description="用户ID（整数类型，对应calendar_user_id）")
):
    """
    创建待办聊天会话
    
    为指定待办创建一个新的AI聊天会话。
    
    ⚠️ 重要说明：
    - X-USER-ID 是整数类型，对应 calendar_user_id
    - content 是必填参数，必须提供初始用户消息
    - 如果不提供 title，系统会基于用户初始消息自动生成会话标题
    - 使用 ReAct (Reasoning + Acting) 架构进行任务规划和AI回复
    
    参数说明：
    - **event_id**: 待办事件ID
    - **content**: 初始用户消息（必选）
    - **title**: 会话标题（可选，不提供则自动生成）
    - **todo_content**: 当前待办的正文内容（Markdown格式）
    - **rich_cards**: 当前待办关联的富媒体卡片列表
    """
    logger.info(f"📝 创建待办聊天会话请求: event_id={event_id}, user_id={x_user_id}, content={request.content[:50]}...")
    
    try:
        # 验证用户
        user_info = get_user_by_header(x_user_id)
        calendar_user_id = user_info["calendar_user_id"]
        
        # 获取聊天管理器和AI Agent
        chat_manager = get_todo_chat_manager()
        todo_agent = get_todo_chat_agent()
        
        # 检查工具是否已加载，如果没有则强制重新初始化
        if hasattr(todo_agent, 'function_map') and len(todo_agent.function_map) == 0:
            logger.warning("⚠️ TodoChatAgent没有工具，尝试重新初始化...")
            todo_agent = get_todo_chat_agent(force_reinit=True)
        
        # 如果没有提供标题，使用AI生成标题
        session_title = request.title
        if not session_title:
            logger.info("📝 未提供会话标题，使用AI生成...")
            session_title = todo_agent.generate_session_title(request.content)
            logger.info(f"✅ 生成会话标题: {session_title}")
        
        # 创建会话
        session = chat_manager.create_session(
            event_id=event_id,
            user_id=calendar_user_id,
            title=session_title,
            todo_content=request.todo_content,
            rich_cards=request.rich_cards
        )
        
        # 添加用户消息
        user_msg = chat_manager.add_message(
            session_id=session.session_id,
            role="user",
            content=request.content
        )
        
        # 使用ReAct架构的AI Agent生成回复
        logger.info("🤖 使用TodoChatAgent生成AI回复...")
        
        # 准备对话历史（新会话暂时没有历史）
        history = []
        
        # 准备富媒体卡片数据
        rich_cards_data = request.rich_cards if request.rich_cards else []
        
        # 调用AI Agent
        ai_response = await todo_agent.chat_async(
            user_message=request.content,
            todo_content=request.todo_content,
            rich_cards=rich_cards_data,
            history=history
        )
        
        # 解析AI回复，提取结构化内容
        parsed_response = todo_agent.parse_response(ai_response)
        
        logger.info(f"✅ AI回复生成完成: {parsed_response['content'][:100]}...")
        
        # 添加AI回复到会话
        ai_msg = chat_manager.add_message(
            session_id=session.session_id,
            role="assistant",
            content=parsed_response["content"],
            todo_content=parsed_response.get("todo_content"),
            suggested_todos=parsed_response.get("suggested_todos", []),
            rich_cards=parsed_response.get("rich_cards", [])
        )
        
        # 构建响应数据
        response_data = {
            "session_id": session.session_id,
            "event_id": session.event_id,
            "title": session.title,
            "created_at": session.created_at,
            "reply": {
                "message_id": ai_msg.message_id if ai_msg else None,
                "content": parsed_response["content"],
                "todo_content": parsed_response.get("todo_content"),
                "suggested_todos": parsed_response.get("suggested_todos", []),
                "rich_cards": parsed_response.get("rich_cards", [])
            }
        }
        
        logger.info(f"✅ 待办聊天会话创建成功: session_id={session.session_id}, title={session.title}")
        
        return CreateTodoChatSessionResponse(
            code=0,
            message="success",
            data=response_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 创建待办聊天会话失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return CreateTodoChatSessionResponse(
            code=500,
            message=f"服务器错误: {str(e)}",
            data=None
        )


@router.get("/todo/{event_id}/chat/sessions")
async def list_todo_chat_sessions(
    event_id: int,
    x_user_id: int = Header(..., alias="x-user-id", description="用户ID（整数类型，对应calendar_user_id）"),
    page: int = 1,
    page_size: int = 20
):
    """
    获取待办的聊天会话列表
    
    - **event_id**: 待办事件ID
    - **page**: 页码，默认1
    - **page_size**: 每页数量，默认20
    """
    logger.info(f"📋 获取待办聊天会话列表: event_id={event_id}, user_id={x_user_id}")
    
    try:
        # 验证用户
        user_info = get_user_by_header(x_user_id)
        calendar_user_id = user_info["calendar_user_id"]
        
        # 获取聊天管理器
        chat_manager = get_todo_chat_manager()
        
        # 获取会话列表
        sessions = chat_manager.get_sessions_by_event(event_id, calendar_user_id)
        
        # 分页
        total = len(sessions)
        start = (page - 1) * page_size
        end = start + page_size
        paged_sessions = sessions[start:end]
        
        # 构建响应
        session_list = []
        for session in paged_sessions:
            # 构建 last_message 对象（根据API文档，应该是JSON对象）
            last_message = None
            if session.messages:
                last_msg = session.messages[-1]
                last_message = {
                    "role": last_msg.role,
                    "content": last_msg.content,
                    "timestamp": last_msg.timestamp
                }
            
            session_list.append({
                "session_id": session.session_id,
                "event_id": session.event_id,
                "title": session.title,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "message_count": len(session.messages),
                "last_message": last_message
            })
        
        return {
            "code": 0,
            "message": "success",
            "data": {
                "total": total,
                "page": page,
                "page_size": page_size,
                "sessions": session_list
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取待办聊天会话列表失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "code": 500,
            "message": f"服务器错误: {str(e)}",
            "data": None
        }


@router.get("/todo/{event_id}/chat/sessions/{session_id}")
async def get_todo_chat_session(
    event_id: int,
    session_id: str,
    x_user_id: int = Header(..., alias="x-user-id", description="用户ID（整数类型，对应calendar_user_id）"),
    include_messages: bool = True,
    message_limit: int = 50
):
    """
    获取待办聊天会话详情及历史消息
    
    根据API文档，返回格式包含：
    - session: 会话基本信息
    - event: 关联的待办事项信息
    - messages: 历史消息列表（当 include_messages=true 时返回）
    
    - **event_id**: 待办事件ID
    - **session_id**: 会话ID
    - **include_messages**: 是否包含历史消息，默认true
    - **message_limit**: 消息数量限制，默认50
    """
    logger.info(f"📋 获取待办聊天会话详情: session_id={session_id}, include_messages={include_messages}, message_limit={message_limit}")
    
    try:
        # 验证用户
        user_info = get_user_by_header(x_user_id)
        calendar_user_id = user_info["calendar_user_id"]
        
        # 获取聊天管理器
        chat_manager = get_todo_chat_manager()
        
        # 获取会话
        session = chat_manager.get_session(session_id)
        
        if not session:
            return {
                "code": 404,
                "message": "会话不存在",
                "data": None
            }
        
        # 验证权限
        if session.user_id != calendar_user_id or session.event_id != event_id:
            return {
                "code": 403,
                "message": "无权访问此会话",
                "data": None
            }
        
        # 构建 session 对象（根据API文档格式）
        session_obj = {
                "session_id": session.session_id,
                "title": session.title,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
            "message_count": len(session.messages)
        }
        
        # 尝试从日历MCP获取待办事项信息
        event_obj = None
        try:
            calendar_manager = CalendarEventManager(user_id=calendar_user_id)
            # 查询事件，尝试找到对应event_id的事件
            result_str = calendar_manager.query_events(
                timezone="Asia/Shanghai",
                range_start=None,
                range_end=None
            )
            
            # 解析结果
            if isinstance(result_str, str):
                result = json.loads(result_str)
            else:
                result = result_str
            
            # 从事件列表中查找对应event_id的事件
            events = []
            if isinstance(result, dict):
                events = result.get("eventInstanceList", result.get("instances", result.get("events", [])))
            elif isinstance(result, list):
                events = result
            
            # 查找匹配的事件
            matched_event = None
            for evt in events:
                evt_id = None
                if isinstance(evt, dict):
                    evt_id = evt.get("id") or evt.get("event_id") or evt.get("eventId")
                if evt_id == event_id:
                    matched_event = evt
                    break
            
            if matched_event:
                # 构建event对象
                event_obj = {
                    "event_id": event_id,
                    "title": matched_event.get("title") or matched_event.get("summary") or "未命名待办",
                    "event_date_time": matched_event.get("eventDateTime") or matched_event.get("start_time") or matched_event.get("startTime"),
                    "duration": matched_event.get("duration", 3600),
                    "description": matched_event.get("description") or matched_event.get("summary"),
                    "todo_content": session.todo_content,  # 使用会话中存储的待办内容
                    "rich_cards": session.rich_cards  # 使用会话中存储的富媒体卡片
                }
            else:
                # 如果找不到事件，使用基本信息
                logger.warning(f"⚠️ 未找到event_id={event_id}的待办事项，使用基本信息")
                event_obj = {
                    "event_id": event_id,
                    "title": "待办事项",
                    "event_date_time": None,
                    "duration": 3600,
                    "description": None,
                "todo_content": session.todo_content,
                    "rich_cards": session.rich_cards
                }
        except Exception as e:
            logger.warning(f"⚠️ 获取待办事项信息失败: {e}，使用基本信息")
            # 如果获取失败，使用基本信息
            event_obj = {
                "event_id": event_id,
                "title": "待办事项",
                "event_date_time": None,
                "duration": 3600,
                "description": None,
                "todo_content": session.todo_content,
                "rich_cards": session.rich_cards
            }
        
        # 构建消息列表（根据include_messages参数）
        messages = []
        if include_messages:
            # 限制消息数量
            message_list = session.messages[-message_limit:] if len(session.messages) > message_limit else session.messages
            messages = [msg.to_dict() for msg in message_list]
        
        # 构建响应（根据API文档格式）
        return {
            "code": 0,
            "message": "success",
            "data": {
                "session": session_obj,
                "event": event_obj,
                "messages": messages if include_messages else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取待办聊天会话详情失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "code": 500,
            "message": f"服务器错误: {str(e)}",
            "data": None
        }


# ==================== 在指定会话中发送消息 ====================

class SendTodoChatMessageRequest(BaseModel):
    """在指定会话中发送消息请求"""
    content: str = Field(..., description="用户本次发送的消息内容")
    todo_content: Optional[str] = Field(default=None, description="当前待办的正文内容（如果有更新）")
    rich_cards: Optional[List[Dict[str, Any]]] = Field(default=None, description="当前待办关联的富媒体卡片列表")


@router.post("/todo/{event_id}/chat/sessions/{session_id}/messages")
async def send_todo_chat_message(
    event_id: int,
    session_id: str,
    request: SendTodoChatMessageRequest,
    x_user_id: int = Header(..., alias="x-user-id", description="用户ID（整数类型，对应calendar_user_id）")
):
    """
    在指定会话中发送消息，获取AI回复
    
    服务端自动维护会话历史，客户端只需发送当前这一条新消息即可。
    
    服务端处理流程：
    1. 根据 session_id 从数据库获取该会话的完整历史消息
    2. 将历史消息 + 当前新消息 + 待办内容一起发送给AI
    3. AI基于完整上下文生成回复
    4. 服务端保存用户消息和AI回复到数据库
    5. 返回AI回复给客户端
    
    参数说明：
    - **event_id**: 待办事件ID
    - **session_id**: 会话ID
    - **content**: 用户本次发送的消息内容（只需发送当前这一条）
    - **todo_content**: 当前待办的正文内容（如果有更新，需要传入最新的）
    - **rich_cards**: 当前待办关联的富媒体卡片列表（如果有更新，需要传入最新的）
    """
    logger.info(f"💬 在会话中发送消息: session_id={session_id}, event_id={event_id}, user_id={x_user_id}")
    
    try:
        # 验证用户
        user_info = get_user_by_header(x_user_id)
        calendar_user_id = user_info["calendar_user_id"]
        
        # 获取聊天管理器和AI Agent
        chat_manager = get_todo_chat_manager()
        todo_agent = get_todo_chat_agent()
        
        # 检查工具是否已加载，如果没有则强制重新初始化
        if hasattr(todo_agent, 'function_map') and len(todo_agent.function_map) == 0:
            logger.warning("⚠️ TodoChatAgent没有工具，尝试重新初始化...")
            todo_agent = get_todo_chat_agent(force_reinit=True)
        
        # 获取会话
        session = chat_manager.get_session(session_id)
        
        if not session:
            return {
                "code": 404,
                "message": "会话不存在",
                "data": None
            }
        
        # 验证权限
        if session.user_id != calendar_user_id or session.event_id != event_id:
            return {
                "code": 403,
                "message": "无权访问此会话",
                "data": None
            }
        
        # 添加用户消息
        user_msg = chat_manager.add_message(
            session_id=session_id,
            role="user",
            content=request.content
        )
        
        # 获取会话历史消息，转换为AI需要的格式
        history = []
        for msg in session.messages[:-1]:  # 排除刚添加的用户消息
            history.append({
                "role": msg.role,
                "content": msg.content
            })
        
        logger.info(f"📜 会话历史消息数: {len(history)}")
        
        # 使用ReAct架构的AI Agent生成回复
        logger.info("🤖 使用TodoChatAgent生成AI回复...")
        
        # 准备富媒体卡片数据（优先使用请求中的，否则使用会话中的）
        rich_cards_data = request.rich_cards if request.rich_cards else (session.rich_cards or [])
        
        # 准备待办内容（优先使用请求中的，否则使用会话中的）
        todo_content = request.todo_content if request.todo_content else session.todo_content
        
        # 调用AI Agent
        ai_response = await todo_agent.chat_async(
            user_message=request.content,
            todo_content=todo_content,
            rich_cards=rich_cards_data,
            history=history
        )
        
        # 解析AI回复，提取结构化内容
        parsed_response = todo_agent.parse_response(ai_response)
        
        logger.info(f"✅ AI回复生成完成: {parsed_response['content'][:100]}...")
        
        # 添加AI回复到会话
        ai_msg = chat_manager.add_message(
            session_id=session_id,
            role="assistant",
            content=parsed_response["content"],
            todo_content=parsed_response.get("todo_content"),
            suggested_todos=parsed_response.get("suggested_todos", []),
            rich_cards=parsed_response.get("rich_cards", [])
        )
        
        # 如果请求中有更新待办内容或卡片，更新会话
        if request.todo_content or request.rich_cards:
            chat_manager.update_session_context(
                session_id=session_id,
                todo_content=request.todo_content,
                rich_cards=request.rich_cards
            )
        
        # 构建响应数据
        response_data = {
            "message_id": ai_msg.message_id if ai_msg else None,
            "content": parsed_response["content"],
            "todo_content": parsed_response.get("todo_content"),
            "suggested_todos": parsed_response.get("suggested_todos", []),
            "rich_cards": parsed_response.get("rich_cards", [])
        }
        
        logger.info(f"✅ 消息发送成功: session_id={session_id}")
        
        return {
            "code": 0,
            "message": "success",
            "data": response_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 发送消息失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "code": 500,
            "message": f"服务器错误: {str(e)}",
            "data": None
        }


@router.get("/todo/{event_id}/chat/sessions/{session_id}/messages")
async def get_todo_chat_messages(
    event_id: int,
    session_id: str,
    x_user_id: int = Header(..., alias="x-user-id", description="用户ID（整数类型，对应calendar_user_id）"),
    limit: int = 50,
    before: Optional[str] = None,
    after: Optional[str] = None
):
    """
    获取会话消息列表（支持分页）
    
    用于加载会话的聊天记录，支持向上滚动加载更多历史消息。
    
    参数说明：
    - **event_id**: 待办事件ID
    - **session_id**: 会话ID
    - **limit**: 每页数量，默认50，最大100
    - **before**: 获取此消息ID之前的消息（用于向上加载更多）
    - **after**: 获取此消息ID之后的消息（用于获取新消息）
    """
    logger.info(f"📋 获取会话消息列表: session_id={session_id}, limit={limit}, before={before}, after={after}")
    
    try:
        # 验证用户
        user_info = get_user_by_header(x_user_id)
        calendar_user_id = user_info["calendar_user_id"]
        
        # 获取聊天管理器
        chat_manager = get_todo_chat_manager()
        
        # 获取会话
        session = chat_manager.get_session(session_id)
        
        if not session:
            return {
                "code": 404,
                "message": "会话不存在",
                "data": None
            }
        
        # 验证权限
        if session.user_id != calendar_user_id or session.event_id != event_id:
            return {
                "code": 403,
                "message": "无权访问此会话",
                "data": None
            }
        
        # 限制最大数量
        limit = min(limit, 100)
        
        # 获取消息列表
        messages = session.messages
        
        # 处理分页
        if before:
            # 找到before消息的索引
            before_idx = None
            for i, msg in enumerate(messages):
                if msg.message_id == before:
                    before_idx = i
                    break
            
            if before_idx is not None:
                messages = messages[:before_idx]
                messages = messages[-limit:]  # 取最后limit条
        elif after:
            # 找到after消息的索引
            after_idx = None
            for i, msg in enumerate(messages):
                if msg.message_id == after:
                    after_idx = i
                    break
            
            if after_idx is not None:
                messages = messages[after_idx + 1:]
                messages = messages[:limit]  # 取前limit条
        else:
            # 默认取最新的消息
            messages = messages[-limit:]
        
        # 判断是否还有更多消息
        total_count = len(session.messages)
        has_more = len(session.messages) > limit
        
        if messages:
            oldest_message_id = messages[0].message_id
            newest_message_id = messages[-1].message_id
        else:
            oldest_message_id = None
            newest_message_id = None
        
        return {
            "code": 0,
            "message": "success",
            "data": {
                "messages": [msg.to_dict() for msg in messages],
                "has_more": has_more,
                "oldest_message_id": oldest_message_id,
                "newest_message_id": newest_message_id,
                "total": total_count
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取会话消息列表失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "code": 500,
            "message": f"服务器错误: {str(e)}",
            "data": None
        }


@router.post("/todo/{event_id}/chat/sessions/{session_id}/delete")
async def delete_todo_chat_session(
    event_id: int,
    session_id: str,
    x_user_id: int = Header(..., alias="x-user-id", description="用户ID（整数类型，对应calendar_user_id）")
):
    """
    删除待办聊天会话
    
    - **event_id**: 待办事件ID
    - **session_id**: 会话ID
    """
    logger.info(f"🗑️ 删除待办聊天会话: session_id={session_id}")
    
    try:
        # 验证用户
        user_info = get_user_by_header(x_user_id)
        calendar_user_id = user_info["calendar_user_id"]
        
        # 获取聊天管理器
        chat_manager = get_todo_chat_manager()
        
        # 获取会话验证权限
        session = chat_manager.get_session(session_id)
        
        if not session:
            return {
                "code": 404,
                "message": "会话不存在",
                "data": None
            }
        
        # 验证权限
        if session.user_id != calendar_user_id or session.event_id != event_id:
            return {
                "code": 403,
                "message": "无权删除此会话",
                "data": None
            }
        
        # 删除会话
        success = chat_manager.delete_session(session_id)
        
        if success:
            return {
                "code": 0,
                "message": "success",
                "data": {"deleted": True}
            }
        else:
            return {
                "code": 500,
                "message": "删除失败",
                "data": None
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 删除待办聊天会话失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "code": 500,
            "message": f"服务器错误: {str(e)}",
            "data": None
        }


class UpdateSessionTitleRequest(BaseModel):
    """更新会话标题请求"""
    title: str = Field(..., description="新标题")


@router.post("/todo/{event_id}/chat/sessions/{session_id}/update-title")
async def update_todo_chat_session_title(
    event_id: int,
    session_id: str,
    request: UpdateSessionTitleRequest,
    x_user_id: int = Header(..., alias="x-user-id", description="用户ID（整数类型，对应calendar_user_id）")
):
    """
    更新待办聊天会话标题
    
    路径：`/api/v1/todo/{event_id}/chat/sessions/{session_id}/update-title`
    请求参数通过POST body传递JSON格式：{"title": "新标题"}
    
    - **event_id**: 待办事件ID
    - **session_id**: 会话ID
    - **title**: 新标题（通过POST body传递）
    """
    logger.info(f"📝 更新待办聊天会话标题: session_id={session_id}, new_title={request.title}")
    
    try:
        # 验证用户
        user_info = get_user_by_header(x_user_id)
        calendar_user_id = user_info["calendar_user_id"]
        
        # 获取聊天管理器
        chat_manager = get_todo_chat_manager()
        
        # 获取会话验证权限
        session = chat_manager.get_session(session_id)
        
        if not session:
            return {
                "code": 404,
                "message": "会话不存在",
                "data": None
            }
        
        # 验证权限
        if session.user_id != calendar_user_id or session.event_id != event_id:
            return {
                "code": 403,
                "message": "无权更新此会话",
                "data": None
            }
        
        # 更新标题
        success = chat_manager.update_session_title(session_id, request.title)
        
        if success:
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "session_id": session_id,
                    "title": request.title
                }
            }
        else:
            return {
                "code": 500,
                "message": "更新失败",
                "data": None
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 更新待办聊天会话标题失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "code": 500,
            "message": f"服务器错误: {str(e)}",
            "data": None
        }


# ==================== 富媒体卡片接口 ====================

class CreateRichCardRequest(BaseModel):
    """创建富媒体卡片请求"""
    card_type: str = Field(..., description="卡片类型")
    title: str = Field(..., description="卡片标题")
    subtitle: Optional[str] = Field(default=None, description="副标题")
    icon: Optional[str] = Field(default=None, description="图标")
    data: Optional[Dict[str, Any]] = Field(default=None, description="卡片数据")
    source: Optional[str] = Field(default=None, description="数据来源")
    expires_at: Optional[str] = Field(default=None, description="过期时间")


class UpdateRichCardRequest(BaseModel):
    """更新富媒体卡片请求"""
    title: Optional[str] = Field(default=None, description="卡片标题")
    subtitle: Optional[str] = Field(default=None, description="副标题")
    icon: Optional[str] = Field(default=None, description="图标")
    data: Optional[Dict[str, Any]] = Field(default=None, description="卡片数据")
    source: Optional[str] = Field(default=None, description="数据来源")
    expires_at: Optional[str] = Field(default=None, description="过期时间")


@router.get("/todo/cards/types")
async def get_card_types():
    """
    获取支持的富媒体卡片类型列表
    """
    return {
        "code": 0,
        "message": "success",
        "data": {
            "types": CARD_TYPES
        }
    }


@router.post("/todo/{event_id}/cards")
async def create_rich_card(
    event_id: int,
    request: CreateRichCardRequest,
    x_user_id: int = Header(..., alias="x-user-id", description="用户ID（整数类型，对应calendar_user_id）")
):
    """
    创建富媒体卡片
    
    - **event_id**: 关联的待办事件ID
    - **card_type**: 卡片类型（weather/navigation/ride_hailing等）
    - **title**: 卡片标题
    - **data**: 卡片数据（JSON对象）
    """
    logger.info(f"📝 创建富媒体卡片: event_id={event_id}, type={request.card_type}, title={request.title}")
    
    try:
        # 验证用户
        user_info = get_user_by_header(x_user_id)
        calendar_user_id = user_info["calendar_user_id"]
        
        # 获取卡片管理器
        card_manager = get_rich_card_manager()
        
        # 创建卡片
        card = card_manager.create_card(
            event_id=event_id,
            user_id=calendar_user_id,
            card_type=request.card_type,
            title=request.title,
            subtitle=request.subtitle,
            icon=request.icon,
            data=request.data,
            source=request.source,
            expires_at=request.expires_at
        )
        
        return {
            "code": 0,
            "message": "success",
            "data": card.to_dict()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 创建富媒体卡片失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "code": 500,
            "message": f"服务器错误: {str(e)}",
            "data": None
        }


@router.get("/todo/{event_id}/cards")
async def get_cards_by_event(
    event_id: int,
    x_user_id: int = Header(..., alias="x-user-id", description="用户ID（整数类型，对应calendar_user_id）"),
    card_type: Optional[str] = None
):
    """
    获取待办的所有富媒体卡片
    
    - **event_id**: 待办事件ID
    - **card_type**: 可选，过滤卡片类型
    """
    logger.info(f"📋 获取待办富媒体卡片: event_id={event_id}, type={card_type}")
    
    try:
        # 验证用户
        user_info = get_user_by_header(x_user_id)
        calendar_user_id = user_info["calendar_user_id"]
        
        # 获取卡片管理器
        card_manager = get_rich_card_manager()
        
        # 获取卡片
        cards = card_manager.get_cards_by_event(
            event_id=event_id,
            user_id=calendar_user_id,
            card_type=card_type
        )
        
        return {
            "code": 0,
            "message": "success",
            "data": {
                "total": len(cards),
                "cards": [card.to_dict() for card in cards]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取富媒体卡片失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "code": 500,
            "message": f"服务器错误: {str(e)}",
            "data": None
        }


@router.get("/todo/cards/{card_id}")
async def get_card_by_id(
    card_id: str,
    x_user_id: int = Header(..., alias="x-user-id", description="用户ID（整数类型，对应calendar_user_id）")
):
    """
    根据 card_id 获取富媒体卡片
    
    - **card_id**: 卡片ID
    """
    logger.info(f"📋 获取富媒体卡片: card_id={card_id}")
    
    try:
        # 验证用户
        user_info = get_user_by_header(x_user_id)
        calendar_user_id = user_info["calendar_user_id"]
        
        # 获取卡片管理器
        card_manager = get_rich_card_manager()
        
        # 获取卡片
        card = card_manager.get_card(card_id)
        
        if not card:
            return {
                "code": 404,
                "message": "卡片不存在",
                "data": None
            }
        
        # 验证权限
        if card.user_id != calendar_user_id:
            return {
                "code": 403,
                "message": "无权访问此卡片",
                "data": None
            }
        
        return {
            "code": 0,
            "message": "success",
            "data": card.to_dict()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取富媒体卡片失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "code": 500,
            "message": f"服务器错误: {str(e)}",
            "data": None
        }


@router.post("/todo/cards/{card_id}/update")
async def update_rich_card(
    card_id: str,
    request: UpdateRichCardRequest,
    x_user_id: int = Header(..., alias="x-user-id", description="用户ID（整数类型，对应calendar_user_id）")
):
    """
    更新富媒体卡片
    
    - **card_id**: 卡片ID
    """
    logger.info(f"📝 更新富媒体卡片: card_id={card_id}")
    
    try:
        # 验证用户
        user_info = get_user_by_header(x_user_id)
        calendar_user_id = user_info["calendar_user_id"]
        
        # 获取卡片管理器
        card_manager = get_rich_card_manager()
        
        # 获取卡片验证权限
        card = card_manager.get_card(card_id)
        
        if not card:
            return {
                "code": 404,
                "message": "卡片不存在",
                "data": None
            }
        
        if card.user_id != calendar_user_id:
            return {
                "code": 403,
                "message": "无权更新此卡片",
                "data": None
            }
        
        # 更新卡片
        updated_card = card_manager.update_card(
            card_id=card_id,
            title=request.title,
            subtitle=request.subtitle,
            icon=request.icon,
            data=request.data,
            source=request.source,
            expires_at=request.expires_at
        )
        
        if updated_card:
            return {
                "code": 0,
                "message": "success",
                "data": updated_card.to_dict()
            }
        else:
            return {
                "code": 500,
                "message": "更新失败",
                "data": None
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 更新富媒体卡片失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "code": 500,
            "message": f"服务器错误: {str(e)}",
            "data": None
        }


@router.post("/todo/cards/{card_id}/delete")
async def delete_rich_card(
    card_id: str,
    x_user_id: int = Header(..., alias="x-user-id", description="用户ID（整数类型，对应calendar_user_id）")
):
    """
    删除富媒体卡片
    
    - **card_id**: 卡片ID
    """
    logger.info(f"🗑️ 删除富媒体卡片: card_id={card_id}")
    
    try:
        # 验证用户
        user_info = get_user_by_header(x_user_id)
        calendar_user_id = user_info["calendar_user_id"]
        
        # 获取卡片管理器
        card_manager = get_rich_card_manager()
        
        # 获取卡片验证权限
        card = card_manager.get_card(card_id)
        
        if not card:
            return {
                "code": 404,
                "message": "卡片不存在",
                "data": None
            }
        
        if card.user_id != calendar_user_id:
            return {
                "code": 403,
                "message": "无权删除此卡片",
                "data": None
            }
        
        # 删除卡片
        success = card_manager.delete_card(card_id)
        
        if success:
            return {
                "code": 0,
                "message": "success",
                "data": {"deleted": True}
            }
        else:
            return {
                "code": 500,
                "message": "删除失败",
                "data": None
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 删除富媒体卡片失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "code": 500,
            "message": f"服务器错误: {str(e)}",
            "data": None
        }


def _generate_simple_ai_reply(user_content: str, todo_content: Optional[str] = None) -> str:
    """
    生成简单的AI回复（MVP版本）
    
    后续可接入真正的AI模型
    """
    # MVP版本：简单的模板回复
    if "议程" in user_content or "安排" in user_content:
        return "好的，我已了解您的需求。请问您希望我如何帮您完善这个待办事项的内容？"
    elif "提醒" in user_content:
        return "我会帮您关注这个待办事项。您还需要添加其他信息吗？"
    elif "修改" in user_content or "更新" in user_content:
        return "好的，请告诉我您想要修改的具体内容。"
    else:
        return f"收到您的消息。关于这个待办事项，我可以帮您：\n1. 补充详细内容\n2. 设置提醒\n3. 添加相关信息\n\n请问您需要哪方面的帮助？"


# ==================== SSE流式聊天路由 ====================

class TodoChatSSERequest(BaseModel):
    """待办聊天SSE请求"""
    session_id: Optional[str] = Field(default=None, description="会话ID，为空则创建新会话")
    title: Optional[str] = Field(default=None, description="会话标题（仅创建新会话时有效）")
    content: str = Field(..., description="用户消息内容")
    todo_content: Optional[str] = Field(default=None, description="当前待办正文内容")
    rich_cards: Optional[List[Dict]] = Field(default=None, description="当前富媒体卡片列表")


@router.post("/todo/{event_id}/chat/sessions/stream")
async def todo_chat_stream(
    event_id: int,
    request: TodoChatSSERequest,
    x_user_id: int = Header(..., alias="x-user-id", description="用户ID（整数类型，对应calendar_user_id）")
):
    """
    待办聊天（SSE流式返回）
    
    使用Server-Sent Events (SSE)流式返回AI处理过程，实时展示：
    - AI的思考和规划步骤
    - 工具调用进度
    - 富媒体卡片（立即推送）
    - 聊天内容（打字机效果）
    - 待办内容更新
    - 建议待办列表
    
    **⚠️ 重要说明**：
    1. 如果 session_id 为空，则创建新会话
    2. 如果 session_id 存在，则在现有会话中继续对话
    3. 客户端需要使用 EventSource 或 fetch + ReadableStream 接收SSE事件流
    4. 响应头 Content-Type 为 text/event-stream
    
    **SSE事件类型**：
    - `session_init`: 会话初始化
    - `plan_update`: 执行计划更新
    - `rich_card`: 富媒体卡片
    - `message_delta`: 聊天内容增量
    - `todo_update`: 待办内容更新
    - `suggestions`: 建议待办列表
    - `done`: 处理完成
    - `error`: 错误信息
    
    **参数说明**：
    - **event_id**: 待办事件ID
    - **session_id**: 会话ID（可选）
    - **title**: 会话标题（可选，仅创建新会话时有效）
    - **content**: 用户消息内容（必填）
    - **todo_content**: 当前待办正文内容（可选）
    - **rich_cards**: 当前富媒体卡片列表（可选）
    
    **示例请求**：
    ```bash
    curl -X POST "http://localhost:8080/api/v1/todo/123456/chat/sessions/stream" \\
      -H "Content-Type: application/json" \\
      -H "X-USER-ID: 1001" \\
      -H "Accept: text/event-stream" \\
      -d '{
        "content": "帮我补充会议议程并查询明天的天气",
        "todo_content": "## Q1预算会议\\n\\n### 时间\\n明天下午3点"
      }'
    ```
    """
    logger.info(f"📡 待办聊天SSE流式请求: event_id={event_id}, user_id={x_user_id}, session_id={request.session_id}")
    
    try:
        # 验证用户
        user_info = get_user_by_header(x_user_id)
        calendar_user_id = user_info["calendar_user_id"]
        
        # 获取SSE服务
        sse_service = get_todo_chat_sse_service()
        
        # 创建流式响应
        async def event_generator():
            async for event in sse_service.process_message_stream(
                event_id=event_id,
                user_id=calendar_user_id,
                content=request.content,
                session_id=request.session_id,
                title=request.title,
                todo_content=request.todo_content,
                rich_cards=request.rich_cards or []
            ):
                yield event
        
        # 返回SSE流式响应
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"  # 禁用nginx缓冲
            }
        )
        
    except Exception as e:
        logger.error(f"❌ 待办聊天SSE处理失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"处理失败: {str(e)}"
        )


# 导出路由器
def register_app_api_routes(app):
    """注册APP API路由到FastAPI应用"""
    app.include_router(router)
    logger.info("✅ APP API 路由已注册")

