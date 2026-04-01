#!/usr/bin/env python3
"""
通用聊天API路由
包含所有通用聊天相关的HTTP和WebSocket接口
"""

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request, WebSocket
from loguru import logger
from pydantic import BaseModel, Field

from ty_mem_agent.config.settings import settings

from .general_chat_manager import get_general_chat_manager
from .general_chat_websocket_service import get_general_chat_websocket_service
from .ugc_client import get_ugc_client
from .async_task_manager import get_async_task_manager
from .openclaw_client import (
    get_openclaw_client,
    verify_callback_timestamp,
    verify_openclaw_signature,
)
from .card_island_client import get_card_island_client
from .rich_card_manager import build_async_task_result_card


# ==================== 请求/响应模型 ====================

class BaseResponse(BaseModel):
    """基础响应"""
    code: int = Field(0, description="状态码，0表示成功")
    msg: str = Field("success", description="响应消息")
    data: Dict[str, Any] = Field(default_factory=dict, description="响应数据")


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
    attachments: List[str] = Field(default_factory=list, description="本条消息关联的附件 save_url 列表")


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


# ==================== 附件上传/下载模型 ====================


class ChatAttachmentFileMeta(BaseModel):
    """客户端上传前的文件元数据（映射 UGC FileMeta）"""
    file_name: str = Field(..., description="文件名")
    content_type: str = Field(..., description="文件 MIME 类型，如 text/plain、application/pdf")
    content_length: int = Field(..., ge=0, description="文件大小（字节）")
    content_md5: Optional[str] = Field(None, description="文件 MD5 哈希，Base64 或十六进制编码")


class ChatAttachmentUploadRequest(BaseModel):
    """
    通用聊天附件上传-申请预签名 URL 请求

    前端在真正上传文件到文件服务前，先调用本接口获取保存 URL 和预签名上传 URL。
    """
    file_type: str = Field(..., description="资源类型，对应 UGC 的 resource 字段，如 document、image 等")
    files: List[ChatAttachmentFileMeta] = Field(..., description="待上传文件的元数据列表")


class ChatAttachmentUploadItem(BaseModel):
    """单个附件的上传信息（简化自 UGC FileURL）"""
    save_url: str = Field(..., description="保存 URL（bucket/resource/fileId 格式），后续引用时使用")
    upload_url: str = Field(..., description="预签名上传 URL，前端据此上传文件")
    file_name: Optional[str] = Field(None, description="文件名（冗余给前端展示）")
    content_type: Optional[str] = Field(None, description="文件 MIME 类型")
    content_length: Optional[int] = Field(None, description="文件大小（字节）")


class ChatAttachmentUploadResponse(BaseResponse):
    """附件上传-申请预签名 URL 响应"""
    data: List[ChatAttachmentUploadItem] = Field(default_factory=list, description="每个文件对应的 save_url 与 upload_url 列表")


class ChatAttachmentUseRequest(BaseModel):
    """
    通用聊天附件使用登记请求

    前端在文件成功上传后，调用本接口把 save_url 绑定到业务（例如挂到某个用户或会话下），
    便于后续聊天中引用或展示。
    """
    save_url: str = Field(..., description="文件服务返回的保存 URL（bucket/resource/fileId 格式）")


class ChatAttachmentUseResponse(BaseResponse):
    """附件使用登记响应"""
    data: Dict[str, Any] = Field(default_factory=dict, description="预留字段，目前为空对象")


class ChatAttachmentDownloadItem(BaseModel):
    """单个附件的下载信息"""
    save_url: str = Field(..., description="原始保存 URL")
    download_url: str = Field(..., description="预签名下载 URL，在有效期内可直接下载")


class ChatAttachmentDownloadRequest(BaseModel):
    """
    通用聊天附件-申请预签名下载 URL 请求
    
    前端持有之前的 save_url，调用本接口获取在有效期内可用的下载 URL。
    """
    urls: List[str] = Field(..., description="需要下载的保存 URL 列表（bucket/resource/fileId 格式）")
    max_age: int = Field(3600, ge=60, le=24 * 3600, description="预签名 URL 有效期（秒），默认 1 小时")


class ChatAttachmentDownloadResponse(BaseResponse):
    """附件预签名下载 URL 响应"""
    data: List[ChatAttachmentDownloadItem] = Field(default_factory=list, description="每个保存 URL 对应的下载 URL 列表")


# ==================== 辅助函数 ====================

def _persist_used_attachment(user_id: int, save_url: str) -> None:
    """
    将「附件使用登记」落盘：按用户 ID 存到 data/chat_attachments/used/{user_id}.json。
    便于后续在下载等环节按用户校验或展示已使用附件列表。
    """
    data_dir = Path(settings.DATA_DIR or "").expanduser().resolve()
    if not data_dir:
        data_dir = Path(__file__).resolve().parents[2] / "data"
    used_dir = data_dir / "chat_attachments" / "used"
    used_dir.mkdir(parents=True, exist_ok=True)
    path = used_dir / f"{user_id}.json"
    now = datetime.utcnow().isoformat() + "Z"
    record = {"save_url": save_url, "created_at": now}
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                items = json.load(f)
        else:
            items = []
        items.append(record)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"持久化附件使用记录失败 user_id={user_id} path={path}: {e}")


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


@router.post("/attachments/request-upload", response_model=ChatAttachmentUploadResponse)
async def request_chat_attachment_upload(
    body: ChatAttachmentUploadRequest,
    user_id: int = Header(..., alias="x-user-id"),
):
    """
    【通用聊天】附件上传-申请预签名 URL
    
    注意：
    - 这里只负责调用文件服务获取保存 URL 与预签名上传 URL，本身不接收文件二进制。
    - bucket 固定为 chat，resource 使用 body.file_type。
    - 默认 bucket 固定为 chat，resource 使用 body.file_type。
    - 内部通过 UGCClient 封装调用 UGCService.upload，真正拿到底层文件服务返回的保存 URL 和预签名上传 URL。
    """
    if not body.files:
        raise HTTPException(status_code=400, detail="files 不能为空")

    # 调用 UGC 文件服务，申请上传 URL
    # ugc_client 使用原始 TCP socket（同步阻塞），必须放到线程池避免阻塞事件循环
    ugc_client = get_ugc_client()
    file_list = [
        {
            "file_name": f.file_name,
            "content_type": f.content_type,
            "content_length": f.content_length,
            "content_md5": f.content_md5,
        }
        for f in body.files
    ]
    try:
        upload_result = await asyncio.to_thread(
            lambda: ugc_client.upload(
                bucket="chat",
                resource=body.file_type,
                user_id=user_id,
                max_age=3600,
                file_list=file_list,
            )
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"调用文件服务上传接口失败: {e}")

    # 解析 UGC 返回的 urlList，映射到 ChatAttachmentUploadItem
    url_list = upload_result.get("urlList")
    if not isinstance(url_list, list):
        raise HTTPException(status_code=500, detail="文件服务返回结果缺少 urlList 字段或格式不正确")

    items: List[ChatAttachmentUploadItem] = []
    for meta, file_url in zip(body.files, url_list):
        save_url = file_url.get("url") or file_url.get("saveUrl")
        upload_url = file_url.get("presignedUrl") or file_url.get("uploadUrl")
        if not save_url or not upload_url:
            continue
        items.append(ChatAttachmentUploadItem(
            save_url=save_url,
            upload_url=upload_url,
            file_name=meta.file_name,
            content_type=meta.content_type,
            content_length=meta.content_length,
        ))

    if not items:
        raise HTTPException(status_code=500, detail="文件服务未返回任何可用的上传 URL")

    return ChatAttachmentUploadResponse(code=0, msg="success", data=items)


@router.post("/attachments/use", response_model=ChatAttachmentUseResponse)
async def use_chat_attachment(
    body: ChatAttachmentUseRequest,
    user_id: int = Header(..., alias="x-user-id"),
):
    """
    【通用聊天】附件使用登记

    客户端上传成功后调用本接口，业务服务可选校验 save_url 有效性后，
    将 save_url 与当前用户建立关联并落盘，便于后续下载或权限校验。
    """
    if not body.save_url:
        raise HTTPException(status_code=400, detail="save_url 不能为空")

    ugc = get_ugc_client()
    try:
        validate_result = await asyncio.to_thread(
            lambda: ugc.validate([body.save_url])
        )
    except Exception as e:
        logger.warning(f"UGC validate 调用失败，仍将登记 save_url: {e}")
        validate_result = {}
    # validate 接口有两种可能的响应格式：
    #   新版 Java：{"urlMap": {"<save_url>": {...}}}
    #   已观察到的实际返回：{"fileList": [...]}（fileList 非空表示有效）
    url_map = validate_result.get("urlMap") or validate_result.get("url_map")
    file_list_result = validate_result.get("fileList") or validate_result.get("file_list")

    if url_map is not None:
        # urlMap 格式：key 为 save_url，缺失则无效
        if not isinstance(url_map, dict):
            url_map = {}
        if url_map and body.save_url not in url_map:
            raise HTTPException(
                status_code=400,
                detail="文件服务校验未通过，该 save_url 无效或已失效",
            )
    elif file_list_result is not None:
        # fileList 格式：列表非空表示找到了对应文件记录
        if not isinstance(file_list_result, list) or len(file_list_result) == 0:
            logger.warning(
                f"UGC validate 返回 fileList 为空，save_url 可能尚未入库（忽略继续登记）: "
                f"{body.save_url}"
            )

    _persist_used_attachment(user_id, body.save_url)
    return ChatAttachmentUseResponse(
        code=0,
        msg="success",
        data={"save_url": body.save_url},
    )


@router.post("/attachments/download-url", response_model=ChatAttachmentDownloadResponse)
async def get_chat_attachment_download_urls(
    body: ChatAttachmentDownloadRequest,
    user_id: int = Header(..., alias="x-user-id"),
):
    """
    【通用聊天】附件-申请预签名下载 URL

    入参：客户端传 save_url 列表（body.urls）及可选 max_age；请求头 x-user-id。
    业务服务据此向文件服务申请预签名下载 URL，并返回给客户端用于直接下载。
    """
    if not body.urls:
        raise HTTPException(status_code=400, detail="urls 不能为空")

    ugc = get_ugc_client()
    try:
        download_result = await asyncio.to_thread(
            lambda: ugc.download_external(urls=body.urls, max_age=body.max_age)
        )
    except Exception as e:
        logger.exception("UGC downloadExternal 调用失败")
        raise HTTPException(status_code=502, detail=f"文件服务申请下载 URL 失败: {e}")

    url_list = download_result.get("urlList") or download_result.get("url_list") or []
    if not isinstance(url_list, list):
        raise HTTPException(status_code=502, detail="文件服务返回结果缺少 urlList 或格式不正确")

    items: List[ChatAttachmentDownloadItem] = []
    for entry in url_list:
        save_url = entry.get("url") or entry.get("saveUrl")
        download_url = entry.get("presignedUrl") or entry.get("presigned_url") or entry.get("downloadUrl")
        if not save_url or not download_url:
            continue
        items.append(ChatAttachmentDownloadItem(save_url=save_url, download_url=download_url))

    return ChatAttachmentDownloadResponse(code=0, msg="success", data=items)


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
        summaries = manager.conv_manager.get_user_conversations(
            user_id=str(user_id),
            limit=limit,
            offset=offset,
        )
        session_list = [
            ChatSessionListItem(
                session_id=s["conversation_id"],
                title=s["title"],
                created_at=s["created_at"],
                updated_at=s["updated_at"],
                message_count=s["message_count"],
            )
            for s in summaries
        ]
        
        return GetChatSessionListResponse(
            code=0,
            msg="success",
            data=session_list,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取会话列表失败: {e}", exc_info=True)
        return GetChatSessionListResponse(
            code=1001,
            msg=f"获取会话列表失败: {str(e)}",
            data={},
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
                msg="会话不存在",
                data={},
            )
        
        if session.user_id != user_id:
            return GetChatSessionDetailResponse(
                code=1003,
                msg="无权访问此会话",
                data={},
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
                messages_data = []
                for msg in messages:
                    metadata = msg.metadata or {}
                    messages_data.append(
                        ChatMessageItem(
                            message_id=msg.message_id,
                            role=msg.role,
                            content=msg.content,
                            timestamp=msg.timestamp,
                            rich_cards=metadata.get("rich_cards", []),
                            attachments=metadata.get("attachments", []),
                        )
                    )
                
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
            msg="success",
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
            msg=f"获取会话详情失败: {str(e)}",
            data={},
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
                msg="会话不存在",
            )
        
        if session.user_id != user_id:
            return UpdateSessionTitleResponse(
                code=1003,
                msg="无权访问此会话",
            )
        
        # 更新标题
        success = manager.update_session_title(session_id, request.title)
        
        if success:
            return UpdateSessionTitleResponse(
                code=0,
                msg="success",
                data={},
            )
        else:
            return UpdateSessionTitleResponse(
                code=1004,
                msg="更新标题失败",
                data={},
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 更新会话标题失败: {e}", exc_info=True)
        return UpdateSessionTitleResponse(
            code=1005,
            msg=f"更新会话标题失败: {str(e)}",
            data={},
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
                msg="会话不存在",
                data={},
            )
        
        if session.user_id != user_id:
            return DeleteSessionResponse(
                code=1003,
                msg="无权访问此会话",
                data={},
            )
        
        # 删除会话
        success = manager.delete_session(session_id)
        
        if success:
            return DeleteSessionResponse(
                code=0,
                msg="success",
                data={},
            )
        else:
            return DeleteSessionResponse(
                code=1004,
                msg="删除会话失败",
                data={},
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 删除会话失败: {e}", exc_info=True)
        return DeleteSessionResponse(
            code=1006,
            msg=f"删除会话失败: {str(e)}",
            data={},
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
                msg="会话不存在",
                data={},    
            )
        
        if session.user_id != user_id:
            return GetRichCardsResponse(
                code=1003,
                msg="无权访问此会话",
                data={},   
            )
        
        # 获取卡片列表
        cards = manager.get_session_cards(session_id)
        
        if cards is None:
            return GetRichCardsResponse(
                code=1004,
                msg="获取卡片失败",
                data={},
            )
        
        return GetRichCardsResponse(
            code=0,
            msg="success",
            data=cards
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取富媒体卡片失败: {e}", exc_info=True)
        return GetRichCardsResponse(
            code=1006,
            msg=f"获取富媒体卡片失败: {str(e)}",
            data={},
        )


# ==================== OpenClaw 任务管理 ====================


class OpenClawCallbackRequest(BaseModel):
    """OpenClaw 回调请求体"""
    task_id: str = Field(..., description="OpenClaw 侧任务 ID（即 openclaw_task_id）")
    client_task_id: Optional[str] = Field(None, description="我们提交任务时的 client_task_id，OpenClaw 原样透传，用于快速匹配本地任务")
    status: str = Field(..., description="任务状态：done | failed")
    result: Optional[str] = Field(None, description="任务执行结果（Markdown 格式）")
    error_message: Optional[str] = Field(None, description="失败原因（status=failed 时）")
    next_run_at: Optional[str] = Field(None, description="下次执行时间（ISO 格式，仅周期任务）")
    executed_at: Optional[str] = Field(None, description="本次执行时间（ISO 格式）")


class OpenClawTaskListItem(BaseModel):
    """OpenClaw 任务列表项"""
    task_id: str
    task_type: str
    status: str
    task_description: str
    schedule: Optional[str] = None
    result_summary: Optional[str] = None
    next_run_at: Optional[str] = None
    created_at: str
    updated_at: str


@router.post(
    "/openclaw/callback",
    summary="OpenClaw 任务结果回调",
    description="OpenClaw 任务执行完成后调用此接口，触发卡片岛推送",
    tags=["OpenClaw"],
)
async def openclaw_callback(request: Request):
    """
    接收 OpenClaw 的任务执行结果回调。
    验证 HMAC-SHA256 签名后，更新本地任务状态，并通过卡片岛推送结果给用户。
    """
    if not settings.OPENCLAW_ENABLED:
        # 不读 body、不验签，避免适配层在关闭开关后仍回调时产生无意义处理
        return {"code": 0, "msg": "ignored: openclaw disabled"}

    # 必须先读原始 body 再解析 JSON，保证与发送方 HMAC 使用的字节流一致
    raw_body = await request.body()
    try:
        body = OpenClawCallbackRequest.model_validate_json(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json body")

    timestamp = request.headers.get("X-OpenClaw-Timestamp", "")
    signature = request.headers.get("X-OpenClaw-Signature", "")

    # 配置了密钥时校验时间窗，防止重放（与适配层转发行为一致）
    from ty_mem_agent.config.settings import settings as _settings
    if (_settings.OPENCLAW_CALLBACK_SECRET or "").strip():
        if not verify_callback_timestamp(timestamp):
            raise HTTPException(status_code=401, detail="回调时间戳无效或已过期")

    if not verify_openclaw_signature(raw_body, timestamp, signature):
        logger.warning(f"[OpenClaw Callback] 签名验证失败: task_id={body.task_id}")
        raise HTTPException(status_code=401, detail="签名验证失败")

    task_manager = get_async_task_manager()

    # 根据 client_task_id 或 openclaw_task_id 找到本地任务记录
    # 优先用 client_task_id（我们自己的 ID，直接命中），回退到 openclaw_task_id 反向查询
    local_task = None
    if body.client_task_id:
        local_task = task_manager.get_task(body.client_task_id)
    if not local_task:
        local_task = task_manager.get_task_by_openclaw_id(body.task_id)

    if not local_task:
        logger.warning(f"[OpenClaw Callback] 找不到本地任务: openclaw_task_id={body.task_id}")
        return {"code": 0, "msg": "ignored: task not found locally"}

    # 更新任务状态和结果
    result_text = body.result or body.error_message or ""
    new_status = "done" if body.status == "done" else "failed"
    task_manager.update_result(
        task_id=local_task.task_id,
        result_summary=result_text,
        status=new_status,
        next_run_at=body.next_run_at,
    )

    # 任务成功时：构建结果卡片并通过卡片岛推送给用户
    if new_status == "done" and result_text:
        try:
            card = build_async_task_result_card(
                user_id=local_task.user_id,
                task_id=local_task.task_id,
                task_description=local_task.task_description,
                result_markdown=result_text,
                task_type=local_task.task_type,
                fallback_reason=local_task.fallback_reason,
                next_run_at=body.next_run_at,
                executed_at=body.executed_at,
                session_id=local_task.session_id,
            )
            if card:
                card_detail = json.dumps(card.to_dict(), ensure_ascii=False)
                await asyncio.to_thread(
                    get_card_island_client().publish,
                    local_task.user_id,
                    [{"type": "async_task_result", "detail": card_detail}],
                )
                logger.info(
                    f"[OpenClaw Callback] 结果卡片已推送: task_id={local_task.task_id}, "
                    f"user_id={local_task.user_id}"
                )
        except Exception as e:
            logger.error(f"[OpenClaw Callback] 结果卡片推送失败: {e}", exc_info=True)
    elif new_status == "failed":
        # 失败分支当前不推「成功结果」卡片，仅更新本地任务；联调时请看本日志或 GET /openclaw/tasks
        logger.info(
            f"[OpenClaw Callback] 任务失败已落库（未推送 async_task_result 卡片）: "
            f"task_id={local_task.task_id}, user_id={local_task.user_id}, "
            f"error_message={result_text[:300]!r}"
        )

    return {"code": 0, "msg": "ok", "task_id": local_task.task_id}


@router.get(
    "/openclaw/tasks",
    summary="获取用户的 OpenClaw 异步任务列表",
    tags=["OpenClaw"],
)
async def list_openclaw_tasks(
    user_id: int = Header(..., alias="x-user-id", description="用户ID"),
    status: Optional[str] = Query(None, description="状态过滤：pending|running|done|failed|cancelled"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
):
    """
    获取当前用户提交给 OpenClaw 的异步任务列表。
    """
    if not settings.OPENCLAW_ENABLED:
        return {
            "code": 0,
            "msg": "未开启openclaw能力",
            "data": {"tasks": [], "total": 0},
        }
    try:
        task_manager = get_async_task_manager()
        tasks = task_manager.list_tasks_by_user(
            user_id=user_id, status=status, limit=limit, offset=offset
        )
        return {
            "code": 0,
            "msg": "success",
            "data": {
                "tasks": [
                    OpenClawTaskListItem(
                        task_id=t.task_id,
                        task_type=t.task_type,
                        status=t.status,
                        task_description=t.task_description,
                        schedule=t.schedule,
                        result_summary=t.result_summary,
                        next_run_at=t.next_run_at,
                        created_at=t.created_at,
                        updated_at=t.updated_at,
                    ).model_dump()
                    for t in tasks
                ],
                "total": len(tasks),
            },
        }
    except Exception as e:
        logger.error(f"[OpenClaw] 获取任务列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/openclaw/tasks/{task_id}",
    summary="取消 OpenClaw 异步任务",
    tags=["OpenClaw"],
)
async def cancel_openclaw_task(
    task_id: str,
    user_id: int = Header(..., alias="x-user-id", description="用户ID"),
):
    """
    取消指定的 OpenClaw 异步任务（包括停止定期执行）。
    仅任务所有者可操作。
    """
    try:
        task_manager = get_async_task_manager()
        task = task_manager.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.user_id != user_id:
            raise HTTPException(status_code=403, detail="无权操作此任务")
        if task.status in ("done", "failed", "cancelled"):
            return {"code": 0, "msg": f"任务已处于终态: {task.status}", "data": {}}

        # 同步取消本地状态
        task_manager.cancel_task(task_id)

        # 异步取消 OpenClaw 侧任务（开关关闭时仅本地取消）
        if settings.OPENCLAW_ENABLED and task.openclaw_task_id:
            asyncio.create_task(
                get_openclaw_client().cancel_task(task.openclaw_task_id)
            )

        return {"code": 0, "msg": "任务已取消", "data": {"task_id": task_id}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[OpenClaw] 取消任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 导出 ====================

def get_general_chat_router() -> APIRouter:
    """获取通用聊天路由"""
    return router


def register_general_chat_routes(app):
    """注册通用聊天路由到FastAPI应用"""
    app.include_router(router)
    logger.info("✅ 通用聊天路由已注册")

