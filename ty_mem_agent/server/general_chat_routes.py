#!/usr/bin/env python3
"""
通用聊天API路由
包含所有通用聊天相关的HTTP和WebSocket接口
"""

from typing import List, Optional
from fastapi import APIRouter, Header, WebSocket, HTTPException, Query
from pydantic import BaseModel, Field
from loguru import logger

from .general_chat_manager import get_general_chat_manager
from .general_chat_websocket_service import get_general_chat_websocket_service


# ==================== 请求/响应模型 ====================

class BaseResponse(BaseModel):
    """基础响应"""
    code: int = Field(0, description="状态码，0表示成功")
    message: str = Field("success", description="响应消息")


class ChatSessionListItem(BaseModel):
    """聊天会话列表项"""
    session_id: str = Field(..., description="会话ID")
    title: str = Field(..., description="会话标题")
    created_at: str = Field(..., description="创建时间（ISO 8601格式）")
    updated_at: str = Field(..., description="更新时间（ISO 8601格式）")
    message_count: int = Field(..., description="消息数量")


class GetChatSessionListResponse(BaseResponse):
    """获取会话列表响应"""
    data: Optional[List[ChatSessionListItem]] = None


class UpdateSessionTitleRequest(BaseModel):
    """更新会话标题请求"""
    title: str = Field(..., min_length=1, max_length=50, description="新标题（1-50字）")


class UpdateSessionTitleResponse(BaseResponse):
    """更新会话标题响应"""
    pass


class DeleteSessionResponse(BaseResponse):
    """删除会话响应"""
    pass


class ChatMessageItem(BaseModel):
    """聊天消息项"""
    message_id: str = Field(..., description="消息ID")
    role: str = Field(..., description="角色：user或assistant")
    content: str = Field(..., description="消息内容")
    timestamp: str = Field(..., description="时间戳（ISO 8601格式）")
    rich_cards: List[dict] = Field(default_factory=list, description="富媒体卡片列表")


class GetChatHistoryResponse(BaseResponse):
    """获取聊天历史响应"""
    data: Optional[List[ChatMessageItem]] = None


class GetRichCardsResponse(BaseResponse):
    """获取富媒体卡片响应"""
    data: Optional[List[dict]] = None


class ChatSessionDetail(BaseModel):
    """聊天会话详情"""
    session_id: str = Field(..., description="会话ID")
    title: str = Field(..., description="会话标题")
    created_at: str = Field(..., description="创建时间（ISO 8601格式）")
    updated_at: str = Field(..., description="更新时间（ISO 8601格式）")
    message_count: int = Field(..., description="消息数量")


class GetChatSessionDetailData(BaseModel):
    """获取会话详情响应数据"""
    session: ChatSessionDetail = Field(..., description="会话信息")
    messages: List[ChatMessageItem] = Field(default_factory=list, description="消息列表")
    has_more: bool = Field(False, description="是否还有更多消息")
    oldest_message_id: Optional[str] = Field(None, description="最早的消息ID")
    newest_message_id: Optional[str] = Field(None, description="最新的消息ID")


class GetChatSessionDetailResponse(BaseResponse):
    """获取会话详情响应"""
    data: Optional[GetChatSessionDetailData] = None


# ==================== 辅助函数 ====================

def get_user_by_header(x_user_id: int = Header(..., alias="x-user-id")) -> int:
    """
    从请求头获取用户ID
    
    Args:
        x_user_id: 请求头中的用户ID
        
    Returns:
        用户ID
        
    Raises:
        HTTPException: 如果用户ID无效
    """
    if not x_user_id or x_user_id <= 0:
        raise HTTPException(status_code=401, detail="无效的用户ID")
    return x_user_id


# ==================== 路由定义 ====================

router = APIRouter(
    prefix="/agent/api/v1/chat",
    tags=["通用聊天"]
)


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: int = Query(..., alias="user_id", description="用户ID")
):
    """
    WebSocket连接端点
    
    用于实时聊天、TTS等
    
    Query参数：
        user_id: 用户ID（必需）
    
    客户端消息格式：
    ```json
    {
        "type": "send_message",
        "session_id": "可选，不提供则创建新会话",
        "message": "用户消息内容",
        "enable_tts": false,
        "tts_config": {
            "voice": "Cherry",
            "format": "mp3",
            "sample_rate": 24000,
            "volume": 50,
            "speech_rate": 1.0,
            "pitch_rate": 1.0
        },
        "client_type": "app",
        "deep_thinking": false
    }
    ```
    
    服务端消息类型：
    - connection_established: 连接建立
    - session_created: 会话创建
    - message_received: 消息接收确认
    - generation_started: 生成开始
    - message_delta: 文本增量
    - sentence_complete: 句子完成（TTS）
    - audio_start: 音频开始
    - audio_chunk: 音频数据（二进制）
    - audio_end: 音频结束
    - tool_call: 工具调用
    - tool_result: 工具结果
    - card_generated: 卡片生成
    - generation_completed: 生成完成
    - title_updated: 标题更新
    - error: 错误
    - pong: 心跳响应
    """
    if not user_id or user_id <= 0:
        await websocket.close(code=4001, reason="无效的用户ID")
        return
    
    service = get_general_chat_websocket_service()
    await service.handle_connection(websocket=websocket, user_id=user_id)


@router.get("/sessions", response_model=GetChatSessionListResponse)
async def get_chat_sessions(
    user_id: int = Header(..., alias="x-user-id"),
    limit: int = Query(50, ge=1, le=100, description="返回数量限制"),
    offset: int = Query(0, ge=0, description="偏移量")
):
    """
    获取聊天会话列表
    
    按更新时间倒序返回用户的聊天会话列表
    
    Headers:
        x-user-id: 用户ID（必需）
    
    Query参数：
        limit: 返回数量限制（1-100，默认50）
        offset: 偏移量（默认0）
    
    Returns:
        会话列表
    """
    try:
        user_id = get_user_by_header(user_id)
        
        manager = get_general_chat_manager()
        sessions = manager.get_user_sessions(
            user_id=user_id,
            limit=limit,
            offset=offset
        )
        
        # 转换为响应格式
        session_list = [
            ChatSessionListItem(
                session_id=session.session_id,
                title=session.title,
                created_at=session.created_at,
                updated_at=session.updated_at,
                message_count=len(session.messages)
            )
            for session in sessions
        ]
        
        return GetChatSessionListResponse(
            code=0,
            message="success",
            data=session_list
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取会话列表失败: {e}", exc_info=True)
        return GetChatSessionListResponse(
            code=1001,
            message=f"获取会话列表失败: {str(e)}",
            data=None
        )


@router.get("/sessions/{session_id}", response_model=GetChatSessionDetailResponse)
async def get_chat_session_detail(
    session_id: str,
    user_id: int = Header(..., alias="x-user-id"),
    message_limit: int = Query(50, ge=1, le=200, description="消息数量限制"),
    before: Optional[str] = Query(None, description="获取此消息ID之前的消息"),
    after: Optional[str] = Query(None, description="获取此消息ID之后的消息"),
    include_messages: bool = Query(True, description="是否包含消息列表")
):
    """
    获取聊天会话详情及历史消息
    
    根据文档 3.3 节定义，返回会话信息和消息列表
    
    Headers:
        x-user-id: 用户ID（必需）
    
    Path参数：
        session_id: 会话ID
    
    Query参数：
        message_limit: 消息数量限制（1-200，默认50）
        before: 获取此消息ID之前的消息（用于向上加载更多）
        after: 获取此消息ID之后的消息（用于获取新消息）
        include_messages: 是否包含消息列表（默认true）
    
    Returns:
        会话详情和消息列表
    """
    try:
        user_id = get_user_by_header(user_id)
        
        manager = get_general_chat_manager()
        
        # 验证会话所属
        session = manager.get_session(session_id)
        if not session:
            return GetChatSessionDetailResponse(
                code=1002,
                message="会话不存在",
                data=None
            )
        
        if session.user_id != user_id:
            return GetChatSessionDetailResponse(
                code=1003,
                message="无权访问此会话",
                data=None
            )
        
        # 构建会话信息
        session_info = {
            "session_id": session.session_id,
            "title": session.title,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "message_count": len(session.messages)
        }
        
        # 获取消息列表（如果需要）
        messages_data: List[ChatMessageItem] = []
        has_more = False
        oldest_message_id = None
        newest_message_id = None
        
        if include_messages:
            # 获取消息列表
            messages = manager.get_session_messages(
                session_id=session_id,
                limit=message_limit,
                offset=0  # 这里可以根据before/after参数调整
            )
            
            if messages:
                messages_data = [
                    ChatMessageItem(
                        message_id=msg.message_id,
                        role=msg.role,
                        content=msg.content,
                        timestamp=msg.timestamp,
                        rich_cards=msg.metadata.get("rich_cards", []) if msg.metadata else []
                    )
                    for msg in messages
                ]
                
                # 设置分页信息
                oldest_message_id = messages[0].message_id if messages else None
                newest_message_id = messages[-1].message_id if messages else None
                # TODO: 根据实际消息总数判断has_more
                has_more = len(messages) >= message_limit
        
        # 构建响应数据
        session_detail = ChatSessionDetail(
            session_id=session_info["session_id"],
            title=session_info["title"],
            created_at=session_info["created_at"],
            updated_at=session_info["updated_at"],
            message_count=session_info["message_count"]
        )
        
        return GetChatSessionDetailResponse(
            code=0,
            message="success",
            data=GetChatSessionDetailData(
                session=session_detail,
                messages=messages_data,
                has_more=has_more,
                oldest_message_id=oldest_message_id,
                newest_message_id=newest_message_id
            )
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取会话详情失败: {e}", exc_info=True)
        return GetChatSessionDetailResponse(
            code=1005,
            message=f"获取会话详情失败: {str(e)}",
            data=None
        )


@router.post("/sessions/{session_id}/title", response_model=UpdateSessionTitleResponse)
async def update_session_title(
    session_id: str,
    request: UpdateSessionTitleRequest,
    user_id: int = Header(..., alias="x-user-id")
):
    """
    更新会话标题
    
    Headers:
        x-user-id: 用户ID（必需）
    
    Path参数：
        session_id: 会话ID
    
    Body:
        title: 新标题（1-50字）
    
    Returns:
        操作结果
    """
    try:
        user_id = get_user_by_header(user_id)
        
        manager = get_general_chat_manager()
        
        # 验证会话所属
        session = manager.get_session(session_id)
        if not session:
            return UpdateSessionTitleResponse(
                code=1002,
                message="会话不存在"
            )
        
        if session.user_id != user_id:
            return UpdateSessionTitleResponse(
                code=1003,
                message="无权访问此会话"
            )
        
        # 更新标题
        success = manager.update_session_title(session_id, request.title)
        
        if success:
            return UpdateSessionTitleResponse(
                code=0,
                message="success"
            )
        else:
            return UpdateSessionTitleResponse(
                code=1004,
                message="更新标题失败"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 更新会话标题失败: {e}", exc_info=True)
        return UpdateSessionTitleResponse(
            code=1005,
            message=f"更新会话标题失败: {str(e)}"
        )


@router.post("/sessions/{session_id}/delete", response_model=DeleteSessionResponse)
async def delete_session(
    session_id: str,
    user_id: int = Header(..., alias="x-user-id")
):
    """
    删除会话
    
    Headers:
        x-user-id: 用户ID（必需）
    
    Path参数：
        session_id: 会话ID
    
    Returns:
        操作结果
    """
    try:
        user_id = get_user_by_header(user_id)
        
        manager = get_general_chat_manager()
        
        # 验证会话所属
        session = manager.get_session(session_id)
        if not session:
            return DeleteSessionResponse(
                code=1002,
                message="会话不存在"
            )
        
        if session.user_id != user_id:
            return DeleteSessionResponse(
                code=1003,
                message="无权访问此会话"
            )
        
        # 删除会话
        success = manager.delete_session(session_id)
        
        if success:
            return DeleteSessionResponse(
                code=0,
                message="success"
            )
        else:
            return DeleteSessionResponse(
                code=1004,
                message="删除会话失败"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 删除会话失败: {e}", exc_info=True)
        return DeleteSessionResponse(
            code=1006,
            message=f"删除会话失败: {str(e)}"
        )


@router.get("/sessions/{session_id}/cards", response_model=GetRichCardsResponse)
async def get_rich_cards(
    session_id: str,
    user_id: int = Header(..., alias="x-user-id")
):
    """
    获取会话的富媒体卡片
    
    Headers:
        x-user-id: 用户ID（必需）
    
    Path参数：
        session_id: 会话ID
    
    Returns:
        富媒体卡片列表
    """
    try:
        user_id = get_user_by_header(user_id)
        
        manager = get_general_chat_manager()
        
        # 验证会话所属
        session = manager.get_session(session_id)
        if not session:
            return GetRichCardsResponse(
                code=1002,
                message="会话不存在",
                data=None
            )
        
        if session.user_id != user_id:
            return GetRichCardsResponse(
                code=1003,
                message="无权访问此会话",
                data=None
            )
        
        # 获取卡片列表
        cards = manager.get_session_cards(session_id)
        
        if cards is None:
            return GetRichCardsResponse(
                code=1004,
                message="获取卡片失败",
                data=None
            )
        
        return GetRichCardsResponse(
            code=0,
            message="success",
            data=cards
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取富媒体卡片失败: {e}", exc_info=True)
        return GetRichCardsResponse(
            code=1006,
            message=f"获取富媒体卡片失败: {str(e)}",
            data=None
        )


# ==================== 导出 ====================

def get_general_chat_router() -> APIRouter:
    """获取通用聊天路由"""
    return router


def register_general_chat_routes(app):
    """注册通用聊天路由到FastAPI应用"""
    app.include_router(router)
    logger.info("✅ 通用聊天路由已注册")

