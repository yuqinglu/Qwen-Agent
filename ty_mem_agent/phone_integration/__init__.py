#!/usr/bin/env python3
"""
手机操作集成模块

基于 Open-AutoGLM 实现手机 APP 操作能力
"""

from .autoglm_client import AutoGLMClient, get_autoglm_client
from .device_manager import DeviceManager, get_device_manager

__all__ = [
    "AutoGLMClient",
    "get_autoglm_client",
    "DeviceManager", 
    "get_device_manager",
]

