# -*- coding: utf-8 -*-
"""
会话管理路由

端点（需要 Bearer Token）：
  GET    /conversations                          — 获取会话列表
  POST   /conversations                          — 创建新会话
  GET    /conversations/{id}                     — 获取会话详情
  GET    /conversations/{id}/messages            — 获取会话消息
  PUT    /conversations/{id}/title               — 更新会话标题
  POST   /conversations/{id}/generate-title      — AI 自动生成标题
  DELETE /conversations/{id}                     — 删除会话

注：以上是 /ws/{token} 旧 WebSocket 聊天对应的会话接口。
    新通用聊天（/agent/api/v1/chat/ws）的会话接口在 general_chat_routes.py。
"""

from typing import Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import BaseModel

from .auth_routes import get_current_user


class CreateConversationRequest(BaseModel):
    title: Optional[str] = "新对话"


class UpdateConversationTitleRequest(BaseModel):
    title: str


def create_conversation_router(
    conversation_manager,
    user_current_conversation: Dict[str, str],
    generate_title_fn: Optional[Callable] = None,
) -> APIRouter:
    """
    构造会话管理路由器。

    Args:
        conversation_manager:      ConversationManager 实例
        user_current_conversation: {user_id: conversation_id} 字典（引用传递）
        generate_title_fn:         可选的异步函数，签名 `async (text: str) -> str`，
                                    用于 AI 生成会话标题
    """
    router = APIRouter(prefix="/conversations", tags=["conversations"])

    def _require_owner(conversation, current_user):
        """校验会话归属，不匹配则抛 403。"""
        if not conversation:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
        if conversation.user_id != current_user.user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问此会话")

    @router.get("")
    async def get_conversations(current_user=Depends(get_current_user)):
        """获取用户的所有会话列表"""
        try:
            conversations = conversation_manager.get_user_conversations(
                user_id=current_user.user_id, limit=50
            )
            return {"conversations": conversations, "total": len(conversations)}
        except Exception as e:
            logger.error(f"获取会话列表失败: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    @router.post("")
    async def create_conversation(
        request: CreateConversationRequest,
        current_user=Depends(get_current_user),
    ):
        """创建新会话"""
        try:
            conversation = conversation_manager.create_conversation(
                user_id=current_user.user_id, title=request.title
            )
            user_current_conversation[current_user.user_id] = conversation.conversation_id
            return {
                "conversation_id": conversation.conversation_id,
                "title": conversation.title,
                "created_at": conversation.created_at,
            }
        except Exception as e:
            logger.error(f"创建会话失败: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    @router.get("/{conversation_id}")
    async def get_conversation(
        conversation_id: str,
        current_user=Depends(get_current_user),
    ):
        """获取指定会话的详细信息"""
        try:
            conversation = conversation_manager.get_conversation(conversation_id)
            _require_owner(conversation, current_user)
            return conversation.to_dict()
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"获取会话失败: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    @router.get("/{conversation_id}/messages")
    async def get_conversation_messages(
        conversation_id: str,
        current_user=Depends(get_current_user),
    ):
        """获取指定会话的所有消息"""
        try:
            conversation = conversation_manager.get_conversation(conversation_id)
            _require_owner(conversation, current_user)
            messages = conversation_manager.get_conversation_messages(conversation_id)
            return {
                "conversation_id": conversation_id,
                "messages": messages,
                "total": len(messages),
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"获取会话消息失败: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    @router.put("/{conversation_id}/title")
    async def update_conversation_title(
        conversation_id: str,
        request: UpdateConversationTitleRequest,
        current_user=Depends(get_current_user),
    ):
        """更新会话标题"""
        try:
            conversation = conversation_manager.get_conversation(conversation_id)
            _require_owner(conversation, current_user)
            success = conversation_manager.update_conversation_title(conversation_id, request.title)
            if success:
                return {"message": "标题更新成功", "title": request.title}
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="标题更新失败"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"更新会话标题失败: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    @router.post("/{conversation_id}/generate-title")
    async def generate_conversation_title(
        conversation_id: str,
        current_user=Depends(get_current_user),
    ):
        """使用 AI 自动生成会话标题"""
        try:
            conversation = conversation_manager.get_conversation(conversation_id)
            _require_owner(conversation, current_user)
            user_messages = [msg for msg in conversation.messages if msg.role == "user"]
            if not user_messages:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="会话中没有用户消息"
                )
            first_user_message = user_messages[0].content
            if generate_title_fn:
                title = await generate_title_fn(first_user_message)
            else:
                title = first_user_message[:20] + ("..." if len(first_user_message) > 20 else "")
            conversation_manager.update_conversation_title(conversation_id, title)
            return {"title": title, "conversation_id": conversation_id}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"生成会话标题失败: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    @router.delete("/{conversation_id}")
    async def delete_conversation(
        conversation_id: str,
        current_user=Depends(get_current_user),
    ):
        """删除会话"""
        try:
            conversation = conversation_manager.get_conversation(conversation_id)
            _require_owner(conversation, current_user)
            success = conversation_manager.delete_conversation(conversation_id)
            if success:
                return {"message": "会话删除成功"}
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="会话删除失败"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"删除会话失败: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    return router
