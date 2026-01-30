#!/usr/bin/env python3
"""
TTS (Text-to-Speech) 服务
使用阿里云DashScope的qwen3-tts-flash模型进行语音合成
使用新的MultiModalConversation接口（替代已废弃的SpeechSynthesizer）
"""

import asyncio
import os
from typing import Optional, AsyncIterator, Dict, Any
from dataclasses import dataclass
from loguru import logger
import dashscope

from ty_mem_agent.config.settings import settings


@dataclass
class TTSConfig:
    """
    TTS配置
    
    注意：qwen3-tts-flash仅支持以下参数：
    - text: 要合成的文本
    - voice: 音色（Cherry推荐）
    - language_type: 语言类型（Chinese/English）
    
    不支持的参数：volume、speech_rate、pitch_rate、format等
    输出格式固定：PCM 24kHz, 16bit, mono
    """
    model: str = "qwen3-tts-flash"  # 模型名称
    voice: str = "Cherry"  # 音色
    language_type: str = "Chinese"  # 语言类型: Chinese, English
    
    @classmethod
    def from_settings(cls) -> "TTSConfig":
        """从settings创建配置"""
        return cls(
            model=settings.TTS_MODEL,
            voice=settings.TTS_VOICE,
            language_type=settings.TTS_LANGUAGE_TYPE
        )


class TTSError(Exception):
    """TTS错误"""
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"TTS Error {code}: {message}")


class TTSService:
    """
    TTS服务
    
    使用阿里云DashScope的qwen3-tts-flash模型进行流式语音合成
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        config: Optional[TTSConfig] = None
    ):
        """
        初始化TTS服务
        
        Args:
            api_key: 阿里云百炼API Key，如不提供则从settings获取
            config: TTS配置，如不提供则从settings获取
        """
        self.api_key = api_key or settings.DASHSCOPE_API_KEY
        if not self.api_key:
            raise ValueError("DASHSCOPE_API_KEY 未配置，请在环境变量中设置")
        
        # 使用配置文件中的配置
        self.config = config or TTSConfig.from_settings()
        
        # 设置DashScope API URL（北京地域）
        # 若使用新加坡地域，需替换为：https://dashscope-intl.aliyuncs.com/api/v1
        dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'
        
        logger.info(f"✅ TTS服务初始化完成: model={self.config.model}, voice={self.config.voice}")
    
    async def synthesize_stream(
        self,
        text: str,
        config: Optional[TTSConfig] = None
    ) -> AsyncIterator[bytes]:
        """
        流式语音合成
        
        Args:
            text: 要合成的文本
            config: TTS配置（可选，不提供则使用默认配置）
            
        Yields:
            音频数据块（bytes，PCM格式，16kHz采样率，16bit，单声道）
            
        Note:
            返回的是原始PCM音频数据，不是MP3或其他编码格式。
            PCM格式参数（qwen3-tts-flash固定输出）：
            - 采样率: 24000 Hz (24kHz)
            - 位深: 16 bit
            - 声道: 单声道 (mono)
            - 格式: paInt16 (pyaudio) / AudioFormat.ENCODING_PCM_16BIT (Android)
            
            客户端可直接播放PCM数据，或转换为WAV/MP3格式
        """
        if not text or not text.strip():
            logger.warning("⚠️ TTS输入文本为空")
            return
        
        tts_config = config or self.config
        
        logger.debug(f"🔊 开始TTS合成: text_len={len(text)}, model={tts_config.model}, voice={tts_config.voice}")
        
        try:
            # 使用新的MultiModalConversation接口
            response = dashscope.MultiModalConversation.call(
                model=tts_config.model,
                api_key=self.api_key,
                text=text,
                voice=tts_config.voice,
                language_type=tts_config.language_type,
                stream=True
            )
            
            total_bytes = 0
            
            # 迭代响应chunks
            for chunk in response:
                # 检查是否有错误
                if hasattr(chunk, 'status_code') and chunk.status_code != 200:
                    error_msg = getattr(chunk, 'message', '未知错误')
                    logger.error(f"❌ TTS合成错误: {error_msg}")
                    raise TTSError(1002, f"TTS合成失败: {error_msg}")
                
                # 提取音频数据
                # Audio对象是一个类字典对象，包含'data', 'url', 'id', 'expires_at'等字段
                if hasattr(chunk, 'output') and hasattr(chunk.output, 'audio'):
                    audio = chunk.output.audio
                    if audio and hasattr(audio, 'get'):
                        # 音频数据在audio['data']中，是base64编码的字符串
                        audio_data_base64 = audio.get('data')
                        if audio_data_base64:
                            # Base64解码
                            import base64
                            audio_bytes = base64.b64decode(audio_data_base64)
                            
                            total_bytes += len(audio_bytes)
                            yield audio_bytes
                            
                            logger.debug(f"📦 收到音频块: {len(audio_bytes)} bytes")
            
            logger.debug(f"✅ TTS合成完成: total_bytes={total_bytes}")
            
        except TTSError:
            raise
        except Exception as e:
            logger.error(f"❌ TTS合成失败: {e}", exc_info=True)
            raise TTSError(1004, f"TTS合成失败: {str(e)}")
    
    async def synthesize_sync(
        self,
        text: str,
        config: Optional[TTSConfig] = None
    ) -> bytes:
        """
        同步语音合成（等待完成后返回完整音频）
        
        Args:
            text: 要合成的文本
            config: TTS配置（可选，不提供则使用默认配置）
            
        Returns:
            完整的音频数据
        """
        audio_chunks = []
        async for chunk in self.synthesize_stream(text, config):
            audio_chunks.append(chunk)
        
        return b"".join(audio_chunks)
    
    def get_config(self) -> TTSConfig:
        """获取当前配置"""
        return self.config
    
    def update_config(self, **kwargs):
        """
        更新配置
        
        Args:
            **kwargs: 配置参数
        """
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.debug(f"✅ 更新TTS配置: {key}={value}")


# 全局单例
_tts_service = None


def get_tts_service() -> TTSService:
    """获取TTS服务单例"""
    global _tts_service
    if _tts_service is None:
        _tts_service = TTSService()
    return _tts_service


# ==================== 测试代码 ====================

async def test_tts():
    """测试TTS服务"""
    import sys
    import wave
    from pathlib import Path
    
    # 添加项目根目录到路径
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))
    
    tts = get_tts_service()
    
    # 测试文本
    #text = "你好，我是通用智能助手。很高兴为您服务。"
    text = "小嘟你好啊，今天考试考得好吗？"
    
    print(f"🔊 开始合成: {text}")
    
    # 流式合成
    audio_chunks = []
    async for chunk in tts.synthesize_stream(text):
        audio_chunks.append(chunk)
        print(f"📦 收到音频块: {len(chunk)} bytes")
    
    # 合并音频数据
    pcm_data = b"".join(audio_chunks)
    
    # 创建输出目录
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    
    # 保存PCM原始数据
    pcm_path = data_dir / "test_tts_output.pcm"
    with open(pcm_path, "wb") as f:
        f.write(pcm_data)
    
    print(f"✅ PCM音频已保存到: {pcm_path}")
    print(f"✅ 总大小: {len(pcm_data)} bytes")
    
    # 转换为WAV格式（更通用）
    try:
        wav_path = data_dir / "test_tts_output.wav"
        
        # PCM参数：24kHz, 16bit, mono（这是qwen3-tts-flash的固定输出格式）
        with wave.open(str(wav_path), 'wb') as wav_file:
            wav_file.setnchannels(1)  # 单声道
            wav_file.setsampwidth(2)  # 16bit = 2 bytes
            wav_file.setframerate(24000)  # 24kHz采样率（官方示例使用24000）
            wav_file.writeframes(pcm_data)
        
        print(f"✅ WAV音频已保存到: {wav_path}")
        print(f"💡 使用任意音频播放器播放WAV文件即可")
    except Exception as e:
        print(f"❌ WAV转换失败: {e}")


if __name__ == "__main__":
    asyncio.run(test_tts())

