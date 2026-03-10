# -*- coding: utf-8 -*-
"""
认证路由：用户注册、登录、登出

端点：
  POST /auth/register  — 用户注册
  POST /auth/login     — 用户登录（返回 JWT Token）
  POST /auth/logout    — 用户登出（需要 Bearer Token）
"""

from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from pydantic import BaseModel

from .user_manager import user_manager

security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """验证 JWT Token，返回当前用户对象。"""
    token = credentials.credentials
    user_id = user_manager.verify_access_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = user_manager.get_user(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user


class UserLogin(BaseModel):
    username: str
    password: str


class UserRegister(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


def create_auth_router(
    disconnect_user_callback: Optional[Callable] = None,
) -> APIRouter:
    """
    构造认证路由器。

    Args:
        disconnect_user_callback: 可选的异步回调，签名 `async (user_id: str) -> None`，
                                   登出时用于断开已存在的 WebSocket 连接。
    """
    router = APIRouter(prefix="/auth", tags=["auth"])

    @router.post("/register")
    async def register(user_data: UserRegister):
        """用户注册"""
        user = user_manager.create_user(
            username=user_data.username,
            password=user_data.password,
            email=user_data.email,
        )
        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="用户名已存在或注册失败",
            )
        return {"message": "注册成功", "user_id": user.user_id}

    @router.post("/login")
    async def login(login_data: UserLogin):
        """用户登录，返回 Bearer Token"""
        user = user_manager.authenticate_user(
            username=login_data.username,
            password=login_data.password,
        )
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
            )
        session = user_manager.create_session(user.user_id)
        token = user_manager.create_access_token(user.user_id)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user_id": user.user_id,
            "username": user.username,
            "session_id": session.session_id if session else None,
        }

    @router.post("/logout")
    async def logout(current_user=Depends(get_current_user)):
        """用户登出"""
        session = user_manager.get_user_session(current_user.user_id)
        if session:
            user_manager.end_session(session.session_id)
        if disconnect_user_callback:
            try:
                await disconnect_user_callback(current_user.user_id)
            except Exception as e:
                logger.debug(f"登出时断开 WebSocket 失败（非致命）: {e}")
        return {"message": "登出成功"}

    return router
