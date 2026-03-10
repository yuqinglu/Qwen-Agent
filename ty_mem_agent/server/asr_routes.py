#!/usr/bin/env python3
"""
ASR 语音识别 API 路由
提供WebSocket实时流式语音识别接口

接口设计参考：ty_mem_agent/doc/APP_API_DESIGN.md
"""

import json
import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Header, UploadFile, File, Form, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from loguru import logger

from ty_mem_agent.config.settings import settings
from ty_mem_agent.server.user_manager import user_manager
from ty_mem_agent.server.user_id_mapper import UserIdMapper
from ty_mem_agent.server.asr_service import (
    ASRSessionManager,
    ASRConfig,
    ASRResult,
    ASRError,
    get_asr_session_manager,
    validate_audio_format,
    get_asr_config,
    SUPPORTED_AUDIO_FORMATS
)


# ==================== WebSocket 日志过滤器 ====================

class WebSocketBinaryLogFilter(logging.Filter):
    """过滤WebSocket BINARY消息的日志"""
    
    def filter(self, record: logging.LogRecord) -> bool:
        """
        过滤掉WebSocket的BINARY消息日志
        只保留TEXT消息和其他重要日志
        """
        message = record.getMessage()
        
        # 过滤掉 "< BINARY" 消息（客户端发送的音频数据）
        if "< BINARY" in message:
            return False
        
        # 可选：也过滤掉 "> BINARY" 消息（服务端发送的二进制数据，如果有）
        # if "> BINARY" in message:
        #     return False
        
        return True


# 应用日志过滤器到uvicorn的日志
def setup_websocket_log_filter():
    """设置WebSocket日志过滤器"""
    # 获取uvicorn的logger
    uvicorn_logger = logging.getLogger("uvicorn.access")
    uvicorn_logger.addFilter(WebSocketBinaryLogFilter())
    
    # 也应用到uvicorn.error logger
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    uvicorn_error_logger.addFilter(WebSocketBinaryLogFilter())
    
    logger.info("✅ WebSocket日志过滤器已启用（已过滤BINARY消息）")


# ==================== Pydantic 模型 ====================

class ASRRecognizeResponse(BaseModel):
    """语音识别响应"""
    code: int = Field(default=0, description="响应码")
    message: str = Field(default="success", description="响应消息")
    data: Optional[Dict[str, Any]] = Field(default=None, description="响应数据")


# ==================== API 路由 ====================

# 创建路由器
router = APIRouter(prefix="/agent/api/v1/asr", tags=["ASR语音识别"])


def get_user_by_header(x_user_id: int = Header(..., alias="x-user-id", description="用户ID")) -> Dict[str, Any]:
    """
    通过X-USER-ID头获取用户信息
    """
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
        user_manager.db.update_user(user.user_id, {'calendar_user_id': calendar_user_id})
        user.calendar_user_id = calendar_user_id
    else:
        calendar_user_id = user.calendar_user_id
    
    return {
        "user_id": user.user_id,
        "x_user_id": x_user_id,
        "calendar_user_id": calendar_user_id,
        "user": user
    }


@router.get("/formats")
async def get_supported_formats():
    """
    获取支持的音频格式列表
    """
    return {
        "code": 0,
        "message": "success",
        "data": {
            "formats": SUPPORTED_AUDIO_FORMATS,
            "default_format": settings.ASR_FORMAT,
            "default_sample_rate": settings.ASR_SAMPLE_RATE,
            "default_language": settings.ASR_LANGUAGE
        }
    }


@router.post("/recognize", response_model=ASRRecognizeResponse)
async def recognize_audio(
    audio_file: UploadFile = File(..., description="音频文件"),
    x_user_id: int = Header(..., alias="x-user-id", description="用户ID"),
    format: Optional[str] = Form(default=None, description="音频格式"),
    sample_rate: Optional[int] = Form(default=None, description="采样率"),
    language: Optional[str] = Form(default="zh", description="语言"),
    stream_output: bool = Form(default=False, description="是否流式输出")
):
    """
    语音识别接口（文件上传）
    
    支持流式/非流式输出：
    - stream_output=false: 等待识别完成后一次性返回（适合短音频）
    - stream_output=true: SSE流式返回（适合长音频）
    
    支持的音频格式：wav, mp3, m4a, ogg, opus, flac, aac, amr, pcm
    """
    logger.info(f"🎙️ 语音识别请求: user_id={x_user_id}, filename={audio_file.filename}, stream={stream_output}")
    
    try:
        # 验证用户
        user_info = get_user_by_header(x_user_id)
        
        # 确定音频格式
        if not format:
            # 从文件名推断格式
            if audio_file.filename:
                ext = audio_file.filename.rsplit('.', 1)[-1].lower() if '.' in audio_file.filename else 'pcm'
                format = ext
            else:
                format = settings.ASR_FORMAT
        
        # 验证格式
        if not validate_audio_format(format):
            return ASRRecognizeResponse(
                code=400,
                message=f"不支持的音频格式: {format}，支持的格式: {SUPPORTED_AUDIO_FORMATS}",
                data=None
            )
        
        # 读取音频数据
        audio_data = await audio_file.read()
        
        if len(audio_data) == 0:
            return ASRRecognizeResponse(
                code=400,
                message="音频文件为空",
                data=None
            )
        
        logger.info(f"📦 音频数据大小: {len(audio_data)} bytes")
        
        # 非流式输出模式：使用同步调用
        if not stream_output:
            result = await _recognize_sync(
                audio_data=audio_data,
                format=format,
                sample_rate=sample_rate,
                language=language
            )
            return result
        else:
            # 流式输出模式：返回SSE响应
            return StreamingResponse(
                _recognize_stream(
                    audio_data=audio_data,
                    format=format,
                    sample_rate=sample_rate,
                    language=language
                ),
                media_type="text/event-stream"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 语音识别失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return ASRRecognizeResponse(
            code=500,
            message=f"服务器错误: {str(e)}",
            data=None
        )


async def _recognize_sync(
    audio_data: bytes,
    format: Optional[str],
    sample_rate: Optional[int],
    language: Optional[str]
) -> ASRRecognizeResponse:
    """
    同步语音识别
    
    等待识别完成后返回完整结果
    """
    from ty_mem_agent.server.asr_service import DashscopeASRClient
    
    try:
        # 创建ASR客户端（未指定的参数将使用settings中的默认值）
        config = get_asr_config(format=format, sample_rate=sample_rate, language=language)
        client = DashscopeASRClient(config=config)
        
        # 连接
        if not await client.connect():
            return ASRRecognizeResponse(
                code=1001,
                message="ASR服务连接失败",
                data=None
            )
        
        # 启动识别
        if not await client.start_recognition():
            await client.close()
            return ASRRecognizeResponse(
                code=1001,
                message="ASR识别任务启动失败",
                data=None
            )
        
        # 发送音频数据（分块发送）
        chunk_size = 3200  # 100ms的16kHz PCM数据
        for i in range(0, len(audio_data), chunk_size):
            chunk = audio_data[i:i + chunk_size]
            await client.send_audio_direct(chunk)
            await asyncio.sleep(0.01)  # 短暂延迟，避免发送过快
        
        # 结束识别
        await client.finish_recognition()
        
        # 收集结果
        final_text = ""
        confidence = 0.0
        duration = len(audio_data) / (sample_rate * 2)  # 假设16bit PCM
        
        async for result in client.receive_results():
            if isinstance(result, ASRResult):
                if result.is_final:
                    final_text = result.text
                    confidence = result.confidence or 0.95
            elif isinstance(result, ASRError):
                await client.close()
                return ASRRecognizeResponse(
                    code=1001,
                    message=f"ASR识别错误: {result.message}",
                    data=None
                )
            elif isinstance(result, dict) and result.get("type") == "done":
                break
        
        await client.close()
        
        return ASRRecognizeResponse(
            code=0,
            message="success",
            data={
                "text": final_text,
                "duration": round(duration, 2),
                "confidence": confidence
            }
        )
        
    except Exception as e:
        logger.error(f"❌ 同步识别失败: {e}")
        return ASRRecognizeResponse(
            code=500,
            message=f"识别失败: {str(e)}",
            data=None
        )


async def _recognize_stream(
    audio_data: bytes,
    format: Optional[str],
    sample_rate: Optional[int],
    language: Optional[str]
):
    """
    流式语音识别（SSE生成器）
    """
    from ty_mem_agent.server.asr_service import DashscopeASRClient
    
    try:
        # 创建ASR客户端（未指定的参数将使用settings中的默认值）
        config = get_asr_config(format=format, sample_rate=sample_rate, language=language)
        client = DashscopeASRClient(config=config)
        
        # 连接
        if not await client.connect():
            yield f"event: error\ndata: {json.dumps({'code': 1001, 'message': 'ASR服务连接失败'})}\n\n"
            return
        
        # 启动识别
        if not await client.start_recognition():
            await client.close()
            yield f"event: error\ndata: {json.dumps({'code': 1001, 'message': 'ASR识别任务启动失败'})}\n\n"
            return
        
        # 启动结果接收任务
        result_queue = asyncio.Queue()
        
        async def receive_results():
            async for result in client.receive_results():
                await result_queue.put(result)
        
        receive_task = asyncio.create_task(receive_results())
        
        # 发送音频数据（分块发送）
        chunk_size = 3200
        for i in range(0, len(audio_data), chunk_size):
            chunk = audio_data[i:i + chunk_size]
            await client.send_audio_direct(chunk)
            
            # 检查是否有结果
            try:
                while True:
                    result = result_queue.get_nowait()
                    if isinstance(result, ASRResult):
                        event_type = "final" if result.is_final else "partial"
                        yield f"event: {event_type}\ndata: {json.dumps(result.to_dict(), ensure_ascii=False)}\n\n"
                    elif isinstance(result, ASRError):
                        yield f"event: error\ndata: {json.dumps({'code': result.code, 'message': result.message})}\n\n"
            except asyncio.QueueEmpty:
                pass
            
            await asyncio.sleep(0.01)
        
        # 结束识别
        await client.finish_recognition()
        
        # 等待剩余结果
        while not receive_task.done():
            try:
                result = await asyncio.wait_for(result_queue.get(), timeout=1.0)
                if isinstance(result, ASRResult):
                    event_type = "final" if result.is_final else "partial"
                    yield f"event: {event_type}\ndata: {json.dumps(result.to_dict(), ensure_ascii=False)}\n\n"
                elif isinstance(result, dict) and result.get("type") == "done":
                    break
            except asyncio.TimeoutError:
                break
        
        receive_task.cancel()
        await client.close()
        
        yield f"event: done\ndata: {json.dumps({'status': 'completed'})}\n\n"
        
    except Exception as e:
        logger.error(f"❌ 流式识别失败: {e}")
        yield f"event: error\ndata: {json.dumps({'code': 500, 'message': str(e)})}\n\n"


# ==================== WebSocket 实时流式语音识别 ====================

def register_asr_websocket(app):
    """
    注册ASR WebSocket端点到FastAPI应用
    
    必须通过app实例注册，因为APIRouter不支持WebSocket
    路径使用 /agent 前缀，与其它 APP API 及 Higress 路由保持一致，便于网关转发。
    """
    
    @app.websocket("/agent/api/v1/asr/stream")
    async def asr_stream_websocket(websocket: WebSocket):
        """
        实时流式语音识别 WebSocket 端点
        
        协议说明：
        1. 客户端首先发送初始化消息（JSON）
        2. 然后持续发送音频数据（二进制）
        3. 最后发送结束标记（JSON）
        
        初始化消息格式：
        {
            "type": "init",
            "user_id": 1001,
            "format": "pcm",
            "sample_rate": 16000,
            "language": "zh"
        }
        
        结束消息格式：
        {
            "type": "end"
        }
        
        服务端返回消息类型：
        - ready: 服务就绪
        - partial: 中间识别结果
        - final: 最终识别结果
        - error: 错误消息
        - done: 识别完成
        """
        await websocket.accept()
        logger.info("🎙️ ASR WebSocket连接已建立")
        
        asr_session = None
        user_id = None
        initialized = False
        poll_task = None  # 保存轮询任务的引用
        
        try:
            while True:
                # 接收消息
                message = await websocket.receive()
                
                if message["type"] == "websocket.disconnect":
                    break
                
                if "bytes" in message:
                    # 二进制音频数据
                    if not initialized:
                        await websocket.send_json({
                            "type": "error",
                            "code": 400,
                            "message": "请先发送初始化消息"
                        })
                        continue
                    
                    audio_data = message["bytes"]
                    
                    # 发送音频到ASR服务
                    if asr_session:
                        success = await asr_session.send_audio(audio_data)
                        if not success:
                            logger.error(f"❌ 发送音频失败: session={asr_session.session_id}, size={len(audio_data)}")
                            await websocket.send_json({
                                "type": "error",
                                "code": 1001,
                                "message": "发送音频失败"
                            })
                        # 结果由后台轮询任务 _poll_results 统一处理，避免重复发送
                
                elif "text" in message:
                    # JSON消息
                    try:
                        data = json.loads(message["text"])
                    except json.JSONDecodeError:
                        await websocket.send_json({
                            "type": "error",
                            "code": 400,
                            "message": "无效的JSON格式"
                        })
                        continue
                    
                    msg_type = data.get("type", "")
                    
                    if msg_type == "init":
                        # 初始化消息
                        user_id = data.get("user_id")
                        if not user_id:
                            await websocket.send_json({
                                "type": "error",
                                "code": 401,
                                "message": "缺少user_id"
                            })
                            continue
                        
                        # 验证用户
                        try:
                            get_user_by_header(user_id)
                        except HTTPException as e:
                            await websocket.send_json({
                                "type": "error",
                                "code": e.status_code,
                                "message": e.detail
                            })
                            continue
                        
                        # 创建ASR配置（未指定的参数将使用settings中的默认值）
                        config = get_asr_config(
                            format=data.get("format"),
                            sample_rate=data.get("sample_rate"),
                            language=data.get("language")
                        )
                        
                        # 创建ASR会话
                        session_manager = get_asr_session_manager()
                        asr_session = session_manager.create_session(
                            user_id=user_id,
                            config=config
                        )
                        
                        # 启动ASR会话
                        success = await asr_session.start()
                        if success:
                            initialized = True
                            await websocket.send_json({
                                "type": "ready",
                                "session_id": asr_session.session_id,
                                "message": "ASR服务已就绪，请发送音频数据"
                            })
                            logger.info(f"✅ ASR会话已启动: user_id={user_id}, session_id={asr_session.session_id}")
                            
                            # 启动结果轮询任务（保存任务引用以便后续等待）
                            poll_task = asyncio.create_task(_poll_results(websocket, asr_session))
                        else:
                            await websocket.send_json({
                                "type": "error",
                                "code": 1001,
                                "message": "ASR服务启动失败"
                            })
                    
                    elif msg_type == "config":
                        # 配置消息（可选，在init之后发送）
                        if asr_session:
                            # 更新配置（当前实现不支持动态更新配置）
                            await websocket.send_json({
                                "type": "error",
                                "code": 400,
                                "message": "不支持动态更新配置，请在init时指定"
                            })
                    
                    elif msg_type == "end":
                        # 结束消息
                        logger.info(f"📥 收到end消息: session_id={asr_session.session_id if asr_session else 'None'}")
                        if asr_session:
                            # 调用finish结束识别，触发最终结果返回
                            await asr_session.finish()
                            logger.debug(f"✅ finish()调用完成，等待轮询任务...")
                            
                            # 等待后台轮询任务处理完所有结果（包括最终的final结果）
                            # _poll_results 会在收到 "done" 后自动退出
                            # 等待轮询任务完成，确保所有结果都已发送给客户端
                            if poll_task:
                                try:
                                    # 设置超时以防万一（最多等待5秒）
                                    await asyncio.wait_for(poll_task, timeout=5.0)
                                    logger.info(f"✅ 轮询任务已完成，所有结果已发送")
                                except asyncio.TimeoutError:
                                    logger.warning(f"⚠️ 等待轮询任务超时（5秒），强制取消")
                                    poll_task.cancel()
                            else:
                                logger.warning(f"⚠️ poll_task为None，无法等待")
                            
                            logger.info(f"✅ ASR识别完成: session_id={asr_session.session_id}")
                        break
                    
                    else:
                        await websocket.send_json({
                            "type": "error",
                            "code": 400,
                            "message": f"未知消息类型: {msg_type}"
                        })
        
        except WebSocketDisconnect:
            logger.info(f"📴 ASR WebSocket断开连接: user_id={user_id}")
        except Exception as e:
            logger.error(f"❌ ASR WebSocket错误: {e}")
            import traceback
            logger.error(traceback.format_exc())
            try:
                await websocket.send_json({
                    "type": "error",
                    "code": 500,
                    "message": str(e)
                })
            except:
                pass
        finally:
            # 取消轮询任务（如果还在运行）
            if poll_task and not poll_task.done():
                poll_task.cancel()
                try:
                    await poll_task
                except asyncio.CancelledError:
                    pass
            
            # 清理ASR会话（安全关闭，避免KeyError）
            if asr_session:
                try:
                    session_manager = get_asr_session_manager()
                    await session_manager.close_session(asr_session.session_id)
                except KeyError:
                    # Session已经被删除，忽略
                    logger.debug(f"Session {asr_session.session_id} 已经被清理")
                except Exception as e:
                    logger.error(f"关闭ASR会话时出错: {e}")
            logger.info("📴 ASR WebSocket连接已关闭")


async def _poll_results(websocket: WebSocket, asr_session):
    """
    轮询ASR结果并发送给客户端
    """
    try:
        result_count = 0
        # 注意：也要包括"finished"状态，以便在调用finish()后继续获取最终的final结果
        while asr_session.status in ("ready", "running", "finished"):
            result = await asr_session.get_result(timeout=0.1)
            if result:
                result_count += 1
                result_type = result.get("type", "unknown")
                logger.debug(f"📤 发送ASR结果 #{result_count}: type={result_type}, session={asr_session.session_id}")
                await websocket.send_json(result)
                if result_type == "done":
                    logger.info(f"✅ ASR结果轮询完成，共发送 {result_count} 个结果")
                    break
            await asyncio.sleep(0.05)
    except asyncio.CancelledError:
        logger.info(f"📴 ASR结果轮询任务被取消: session={asr_session.session_id}")
        raise
    except Exception as e:
        logger.warning(f"⚠️ 结果轮询任务出错: {e}, session={asr_session.session_id}")


# ==================== 导出函数 ====================

def register_asr_routes(app):
    """
    注册ASR路由到FastAPI应用
    
    包括：
    - HTTP接口（/api/v1/asr/...）
    - WebSocket接口（/agent/api/v1/asr/stream）
    """
    # 设置WebSocket日志过滤器（过滤BINARY消息）
    setup_websocket_log_filter()
    
    # 注册HTTP路由
    app.include_router(router)
    
    # 注册WebSocket端点
    register_asr_websocket(app)
    
    logger.info("✅ ASR 路由已注册")

