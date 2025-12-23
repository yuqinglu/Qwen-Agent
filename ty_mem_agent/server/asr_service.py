#!/usr/bin/env python3
"""
ASR 语音识别服务
基于阿里云百炼 Fun-ASR 实时语音识别服务

提供WebSocket代理服务，使APP端能够安全地进行实时语音识别，
无需在客户端存储阿里云API Key。

参考文档：
- WebSocket API: https://help.aliyun.com/zh/model-studio/fun-asr-realtime-websocket-api
- Python SDK: https://help.aliyun.com/zh/model-studio/fun-asr-realtime-python-sdk
"""

import asyncio
import json
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

import websockets
from websockets.client import WebSocketClientProtocol
from loguru import logger

from ty_mem_agent.config.settings import settings


# ==================== 从配置获取默认值 ====================

def get_default_asr_ws_url() -> str:
    """获取默认ASR WebSocket URL"""
    return settings.ASR_WS_URL


def get_default_asr_model() -> str:
    """获取默认ASR模型"""
    return settings.ASR_MODEL


def get_default_sample_rate() -> int:
    """获取默认采样率"""
    return settings.ASR_SAMPLE_RATE


def get_default_format() -> str:
    """获取默认音频格式"""
    return settings.ASR_FORMAT


def get_default_language() -> str:
    """获取默认语言"""
    return settings.ASR_LANGUAGE


# ==================== 配置常量 ====================

# 支持的音频格式（固定列表，不通过配置修改）
SUPPORTED_AUDIO_FORMATS = ["pcm", "wav", "mp3", "opus", "speex", "aac", "amr"]


# ==================== 数据类型定义 ====================

class ASRMessageType(str, Enum):
    """ASR消息类型"""
    # 客户端发送的消息类型
    INIT = "init"           # 初始化连接
    CONFIG = "config"       # 配置参数
    AUDIO = "audio"         # 音频数据（二进制）
    END = "end"             # 结束标记
    
    # 服务端返回的消息类型
    PARTIAL = "partial"     # 中间识别结果
    FINAL = "final"         # 最终识别结果
    ERROR = "error"         # 错误消息
    DONE = "done"           # 识别完成
    READY = "ready"         # 服务就绪


@dataclass
class ASRConfig:
    """ASR配置"""
    model: str = None  # 将在__post_init__中从settings获取默认值
    format: str = None  # 将在__post_init__中从settings获取默认值
    sample_rate: int = None  # 将在__post_init__中从settings获取默认值
    language: str = None  # 将在__post_init__中从settings获取默认值，支持 zh, en, ja
    enable_punctuation: bool = True
    enable_inverse_text_normalization: bool = True
    
    def __post_init__(self):
        """初始化默认值"""
        if self.model is None:
            self.model = get_default_asr_model()
        if self.format is None:
            self.format = get_default_format()
        if self.sample_rate is None:
            self.sample_rate = get_default_sample_rate()
        if self.language is None:
            self.language = get_default_language()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "format": self.format,
            "sample_rate": self.sample_rate,
            "language": self.language,
            "enable_punctuation": self.enable_punctuation,
            "enable_inverse_text_normalization": self.enable_inverse_text_normalization
        }


@dataclass
class ASRResult:
    """ASR识别结果"""
    text: str
    is_final: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    sentence_id: Optional[str] = None
    begin_time: Optional[int] = None  # 毫秒
    end_time: Optional[int] = None    # 毫秒
    confidence: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "text": self.text,
            "is_final": self.is_final,
            "timestamp": self.timestamp
        }
        if self.sentence_id:
            result["sentence_id"] = self.sentence_id
        if self.begin_time is not None:
            result["begin_time"] = self.begin_time
        if self.end_time is not None:
            result["end_time"] = self.end_time
        if self.confidence is not None:
            result["confidence"] = self.confidence
        return result


class ASRError(Exception):
    """ASR错误"""
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"ASR Error {code}: {message}")


# ==================== 阿里云百炼ASR客户端 ====================

class DashscopeASRClient:
    """
    阿里云百炼 Fun-ASR WebSocket 客户端
    
    封装与阿里云百炼ASR服务的WebSocket通信
    """
    
    def __init__(
        self, 
        api_key: Optional[str] = None,
        ws_url: Optional[str] = None,
        config: Optional[ASRConfig] = None
    ):
        """
        初始化ASR客户端
        
        Args:
            api_key: 阿里云百炼API Key，如不提供则从settings获取
            ws_url: WebSocket服务地址
            config: ASR配置
        """
        self.api_key = api_key or settings.DASHSCOPE_API_KEY
        if not self.api_key:
            raise ValueError("DASHSCOPE_API_KEY 未配置，请在环境变量中设置")
        
        # 如果没有指定ws_url，则从配置中获取默认值
        self.ws_url = ws_url or get_default_asr_ws_url()
        self.config = config or ASRConfig()
        
        self._ws: Optional[WebSocketClientProtocol] = None
        self._task_id: Optional[str] = None
        self._connected = False
        self._running = False
        
        # 回调函数
        self._on_partial: Optional[Callable[[ASRResult], None]] = None
        self._on_final: Optional[Callable[[ASRResult], None]] = None
        self._on_error: Optional[Callable[[ASRError], None]] = None
        self._on_done: Optional[Callable[[], None]] = None
    
    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None
    
    def set_callbacks(
        self,
        on_partial: Optional[Callable[[ASRResult], None]] = None,
        on_final: Optional[Callable[[ASRResult], None]] = None,
        on_error: Optional[Callable[[ASRError], None]] = None,
        on_done: Optional[Callable[[], None]] = None
    ):
        """设置回调函数"""
        self._on_partial = on_partial
        self._on_final = on_final
        self._on_error = on_error
        self._on_done = on_done
    
    async def connect(self) -> bool:
        """
        连接到阿里云百炼ASR服务
        
        Returns:
            是否连接成功
        """
        if self._connected:
            logger.warning("ASR客户端已连接，无需重复连接")
            return True
        
        try:
            # 构建请求头
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "X-DashScope-DataInspection": "enable"
            }
            
            logger.info(f"🎙️ 正在连接阿里云百炼ASR服务: {self.ws_url}")
            
            # 建立WebSocket连接
            self._ws = await websockets.connect(
                self.ws_url,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10
            )
            
            self._connected = True
            self._task_id = str(uuid.uuid4())
            
            logger.info(f"✅ ASR服务连接成功，task_id: {self._task_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ ASR服务连接失败: {e}")
            self._connected = False
            return False
    
    async def start_recognition(self) -> bool:
        """
        开始语音识别任务
        
        发送 run-task 消息启动识别
        
        Returns:
            是否启动成功
        """
        if not self.is_connected:
            logger.error("ASR服务未连接，无法启动识别")
            return False
        
        try:
            # 构建 run-task 消息
            run_task_message = {
                "header": {
                    "action": "run-task",
                    "task_id": self._task_id,
                    "streaming": "duplex"
                },
                "payload": {
                    "task_group": "audio",
                    "task": "asr",
                    "function": "recognition",
                    "model": self.config.model,
                    "parameters": {
                        "format": self.config.format,
                        "sample_rate": self.config.sample_rate,
                        "language_hints": [self.config.language],
                        "semantic_punctuation_enabled": True,
                        "enable_punctuation": self.config.enable_punctuation,
                        "enable_inverse_text_normalization": self.config.enable_inverse_text_normalization
                    },
                    "input": {}
                }
            }
            
            logger.debug(f"📤 发送 run-task 消息: {json.dumps(run_task_message, ensure_ascii=False)[:200]}...")
            await self._ws.send(json.dumps(run_task_message))
            
            # 等待服务端确认
            response = await asyncio.wait_for(self._ws.recv(), timeout=10)
            
            if isinstance(response, str):
                resp_data = json.loads(response)
                logger.debug(f"📥 收到响应: {resp_data}")
                
                header = resp_data.get("header", {})
                event = header.get("event", "")
                
                if event == "task-started":
                    logger.info("✅ ASR识别任务已启动")
                    self._running = True
                    return True
                elif event == "task-failed":
                    error_code = header.get("error_code", "unknown")
                    error_message = header.get("error_message", "未知错误")
                    logger.error(f"❌ ASR任务启动失败: {error_code} - {error_message}")
                    if self._on_error:
                        self._on_error(ASRError(int(error_code) if error_code.isdigit() else -1, error_message))
                    return False
            
            return True
            
        except asyncio.TimeoutError:
            logger.error("❌ ASR任务启动超时")
            return False
        except Exception as e:
            logger.error(f"❌ ASR任务启动失败: {e}")
            return False
    
    async def send_audio(self, audio_data: bytes) -> bool:
        """
        发送音频数据
        
        Args:
            audio_data: 二进制音频数据
            
        Returns:
            是否发送成功
        """
        if not self.is_connected or not self._running:
            logger.warning("ASR服务未就绪，无法发送音频")
            return False
        
        try:
            # 构建 continue-task 消息（用于发送音频）
            continue_task_message = {
                "header": {
                    "action": "continue-task",
                    "task_id": self._task_id,
                    "streaming": "duplex"
                },
                "payload": {
                    "input": {
                        "audio": ""  # 音频数据将在下一帧发送
                    }
                }
            }
            
            # 先发送元数据消息
            await self._ws.send(json.dumps(continue_task_message))
            
            # 再发送二进制音频数据
            await self._ws.send(audio_data)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 发送音频失败: {e}")
            return False
    
    async def send_audio_direct(self, audio_data: bytes) -> bool:
        """
        直接发送二进制音频数据
        
        适用于已经建立识别任务后的音频流发送
        
        Args:
            audio_data: 二进制音频数据
            
        Returns:
            是否发送成功
        """
        if not self.is_connected or not self._running:
            return False
        
        try:
            await self._ws.send(audio_data)
            return True
        except Exception as e:
            logger.error(f"❌ 发送音频失败: {e}")
            return False
    
    async def finish_recognition(self) -> bool:
        """
        结束语音识别
        
        发送 finish-task 消息
        
        Returns:
            是否成功
        """
        if not self.is_connected:
            return False
        
        try:
            # 构建 finish-task 消息
            finish_task_message = {
                "header": {
                    "action": "finish-task",
                    "task_id": self._task_id,
                    "streaming": "duplex"
                },
                "payload": {
                    "input": {}
                }
            }
            
            logger.info("📤 发送 finish-task 消息，结束识别")
            await self._ws.send(json.dumps(finish_task_message))
            
            self._running = False
            return True
            
        except Exception as e:
            logger.error(f"❌ 结束识别失败: {e}")
            return False
    
    async def receive_results(self):
        """
        接收识别结果（异步生成器）
        
        Yields:
            ASRResult 或 ASRError
        """
        if not self.is_connected:
            return
        
        try:
            async for message in self._ws:
                if isinstance(message, str):
                    # JSON消息
                    data = json.loads(message)
                    result = self._parse_response(data)
                    
                    if result:
                        yield result
                        
                        # 检查是否完成
                        if isinstance(result, dict) and result.get("type") == "done":
                            break
                else:
                    # 二进制消息（忽略）
                    pass
                    
        except websockets.exceptions.ConnectionClosed as e:
            logger.info(f"📴 ASR连接已关闭: {e}")
        except Exception as e:
            logger.error(f"❌ 接收结果失败: {e}")
            yield ASRError(-1, str(e))
    
    def _parse_response(self, data: Dict[str, Any]) -> Optional[Any]:
        """
        解析阿里云百炼响应
        
        Args:
            data: 响应数据
            
        Returns:
            解析后的结果
        """
        header = data.get("header", {})
        payload = data.get("payload", {})
        
        event = header.get("event", "")
        
        if event == "result-generated":
            # 识别结果
            output = payload.get("output", {})
            sentence = output.get("sentence", {})
            
            text = sentence.get("text", "")
            is_final = sentence.get("sentence_end", False)
            begin_time = sentence.get("begin_time")
            end_time = sentence.get("end_time")
            
            result = ASRResult(
                text=text,
                is_final=is_final,
                begin_time=begin_time,
                end_time=end_time
            )
            
            # 调用回调
            if is_final and self._on_final:
                self._on_final(result)
            elif not is_final and self._on_partial:
                self._on_partial(result)
            
            return result
            
        elif event == "task-finished":
            # 任务完成
            logger.info("✅ ASR任务完成")
            if self._on_done:
                self._on_done()
            return {"type": "done", "status": "completed"}
            
        elif event == "task-failed":
            # 任务失败
            error_code = header.get("error_code", "unknown")
            error_message = header.get("error_message", "未知错误")
            error = ASRError(int(error_code) if str(error_code).isdigit() else -1, error_message)
            
            logger.error(f"❌ ASR任务失败: {error}")
            if self._on_error:
                self._on_error(error)
            return error
        
        return None
    
    async def close(self):
        """关闭连接"""
        self._running = False
        self._connected = False
        
        if self._ws:
            try:
                await self._ws.close()
            except Exception as e:
                logger.warning(f"关闭ASR连接时出错: {e}")
            finally:
                self._ws = None
        
        logger.info("📴 ASR客户端已关闭")


# ==================== ASR会话管理 ====================

class ASRSession:
    """
    ASR会话
    
    管理单个用户的ASR会话，作为APP和阿里云ASR服务之间的代理
    """
    
    def __init__(
        self,
        session_id: str,
        user_id: int,
        config: Optional[ASRConfig] = None
    ):
        self.session_id = session_id
        self.user_id = user_id
        self.config = config or ASRConfig()
        self.created_at = datetime.now()
        
        self._client: Optional[DashscopeASRClient] = None
        self._receive_task: Optional[asyncio.Task] = None
        self._result_queue: asyncio.Queue = asyncio.Queue()
        
        self._status = "created"  # created, connecting, ready, running, finished, error
    
    @property
    def status(self) -> str:
        return self._status
    
    async def start(self) -> bool:
        """
        启动ASR会话
        
        Returns:
            是否启动成功
        """
        try:
            self._status = "connecting"
            
            # 创建ASR客户端
            self._client = DashscopeASRClient(config=self.config)
            
            # 注意：不设置回调函数，避免重复处理结果
            # 结果将由 _receive_loop 统一处理并放入队列
            
            # 连接到阿里云ASR服务
            if not await self._client.connect():
                self._status = "error"
                return False
            
            # 启动识别任务
            if not await self._client.start_recognition():
                self._status = "error"
                return False
            
            # 启动结果接收任务（统一处理结果，避免重复）
            self._receive_task = asyncio.create_task(self._receive_loop())
            
            self._status = "ready"
            logger.info(f"✅ ASR会话已启动: session_id={self.session_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ ASR会话启动失败: {e}")
            self._status = "error"
            return False
    
    async def _receive_loop(self):
        """接收结果的循环"""
        try:
            async for result in self._client.receive_results():
                if isinstance(result, ASRResult):
                    await self._result_queue.put({
                        "type": "final" if result.is_final else "partial",
                        "data": result.to_dict()
                    })
                elif isinstance(result, ASRError):
                    await self._result_queue.put({
                        "type": "error",
                        "code": result.code,
                        "message": result.message
                    })
                elif isinstance(result, dict) and result.get("type") == "done":
                    await self._result_queue.put(result)
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"❌ 结果接收循环出错: {e}")
            await self._result_queue.put({
                "type": "error",
                "code": -1,
                "message": str(e)
            })
    
    async def send_audio(self, audio_data: bytes) -> bool:
        """
        发送音频数据
        
        Args:
            audio_data: 二进制音频数据
            
        Returns:
            是否发送成功
        """
        if not self._client or self._status not in ("ready", "running"):
            return False
        
        self._status = "running"
        return await self._client.send_audio_direct(audio_data)
    
    async def get_result(self, timeout: float = 0.1) -> Optional[Dict[str, Any]]:
        """
        获取识别结果（非阻塞）
        
        Args:
            timeout: 超时时间（秒）
            
        Returns:
            识别结果，无结果时返回None
        """
        try:
            return await asyncio.wait_for(self._result_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
    
    async def finish(self) -> bool:
        """
        结束识别
        
        Returns:
            是否成功
        """
        if self._client:
            await self._client.finish_recognition()
        
        self._status = "finished"
        return True
    
    async def close(self):
        """关闭会话"""
        # 取消接收任务
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        
        # 关闭客户端
        if self._client:
            await self._client.close()
        
        self._status = "closed"
        logger.info(f"📴 ASR会话已关闭: session_id={self.session_id}")


class ASRSessionManager:
    """
    ASR会话管理器
    
    管理所有用户的ASR会话
    """
    
    _instance: Optional["ASRSessionManager"] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._sessions: Dict[str, ASRSession] = {}
            cls._instance._user_sessions: Dict[int, str] = {}  # user_id -> session_id
        return cls._instance
    
    def create_session(
        self,
        user_id: int,
        config: Optional[ASRConfig] = None
    ) -> ASRSession:
        """
        创建ASR会话
        
        Args:
            user_id: 用户ID
            config: ASR配置
            
        Returns:
            ASR会话
        """
        # 检查用户是否已有会话
        if user_id in self._user_sessions:
            old_session_id = self._user_sessions[user_id]
            if old_session_id in self._sessions:
                # 关闭旧会话
                asyncio.create_task(self._sessions[old_session_id].close())
                del self._sessions[old_session_id]
        
        # 创建新会话
        session_id = f"asr_{user_id}_{uuid.uuid4().hex[:8]}"
        session = ASRSession(
            session_id=session_id,
            user_id=user_id,
            config=config
        )
        
        self._sessions[session_id] = session
        self._user_sessions[user_id] = session_id
        
        logger.info(f"📝 创建ASR会话: session_id={session_id}, user_id={user_id}")
        return session
    
    def get_session(self, session_id: str) -> Optional[ASRSession]:
        """获取会话"""
        return self._sessions.get(session_id)
    
    def get_session_by_user(self, user_id: int) -> Optional[ASRSession]:
        """根据用户ID获取会话"""
        session_id = self._user_sessions.get(user_id)
        if session_id:
            return self._sessions.get(session_id)
        return None
    
    async def close_session(self, session_id: str):
        """关闭会话"""
        if session_id in self._sessions:
            session = self._sessions[session_id]
            await session.close()
            
            # 清理映射
            if session.user_id in self._user_sessions:
                del self._user_sessions[session.user_id]
            del self._sessions[session_id]
            
            logger.info(f"🗑️ ASR会话已删除: session_id={session_id}")
    
    async def close_all(self):
        """关闭所有会话"""
        for session_id in list(self._sessions.keys()):
            await self.close_session(session_id)
        
        logger.info("🗑️ 所有ASR会话已关闭")


# ==================== 辅助函数 ====================

def get_asr_session_manager() -> ASRSessionManager:
    """获取ASR会话管理器单例"""
    return ASRSessionManager()


def validate_audio_format(format_str: str) -> bool:
    """验证音频格式是否支持"""
    return format_str.lower() in SUPPORTED_AUDIO_FORMATS


def get_asr_config(
    format: Optional[str] = None,
    sample_rate: Optional[int] = None,
    language: Optional[str] = None
) -> ASRConfig:
    """
    获取ASR配置
    
    Args:
        format: 音频格式，如不提供则使用配置中的默认值
        sample_rate: 采样率，如不提供则使用配置中的默认值
        language: 语言，如不提供则使用配置中的默认值
        
    Returns:
        ASR配置对象（未指定的参数将使用settings中的默认值）
    """
    return ASRConfig(
        format=format,
        sample_rate=sample_rate,
        language=language
    )

