#!/usr/bin/env python3
"""
设备管理器

管理虚拟安卓设备（模拟器）的分配和状态
支持多用户场景下的设备池化管理
"""

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger


class DeviceStatus(Enum):
    """设备状态"""
    AVAILABLE = "available"      # 可用
    BUSY = "busy"               # 忙碌中
    OFFLINE = "offline"         # 离线
    ERROR = "error"             # 错误
    MAINTENANCE = "maintenance"  # 维护中


@dataclass
class VirtualDevice:
    """虚拟设备信息"""
    device_id: str                          # 设备 ID，如 emulator-5554
    name: str = ""                          # 设备名称
    status: DeviceStatus = DeviceStatus.AVAILABLE
    assigned_user_id: Optional[str] = None  # 分配的用户 ID
    last_activity: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "status": self.status.value,
            "assigned_user_id": self.assigned_user_id,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata
        }


class DeviceManager:
    """
    设备管理器
    
    管理虚拟安卓设备池，支持：
    - 设备注册和状态管理
    - 用户-设备分配
    - 设备使用统计
    
    MVP 阶段：使用固定设备 emulator-5554
    后续扩展：支持多设备池化管理
    """
    
    def __init__(self):
        """初始化设备管理器"""
        # 设备池
        self._devices: Dict[str, VirtualDevice] = {}
        
        # 用户-设备映射
        self._user_device_map: Dict[str, str] = {}
        
        # 默认设备 ID
        self.default_device_id = os.getenv("AUTOGLM_DEVICE_ID", "emulator-5554")
        
        # 初始化默认设备
        self._init_default_device()
        
        logger.info(f"✅ 设备管理器初始化完成，默认设备: {self.default_device_id}")
    
    def _init_default_device(self):
        """初始化默认设备"""
        default_device = VirtualDevice(
            device_id=self.default_device_id,
            name="默认虚拟设备",
            status=DeviceStatus.AVAILABLE,
            metadata={
                "type": "emulator",
                "android_version": "unknown",
                "is_default": True
            }
        )
        self._devices[self.default_device_id] = default_device
    
    def register_device(
        self,
        device_id: str,
        name: str = "",
        metadata: Dict[str, Any] = None
    ) -> VirtualDevice:
        """
        注册新设备
        
        Args:
            device_id: 设备 ID
            name: 设备名称
            metadata: 设备元数据
        
        Returns:
            VirtualDevice: 注册的设备
        """
        if device_id in self._devices:
            logger.warning(f"⚠️ 设备已存在: {device_id}")
            return self._devices[device_id]
        
        device = VirtualDevice(
            device_id=device_id,
            name=name or f"Device_{device_id}",
            status=DeviceStatus.AVAILABLE,
            metadata=metadata or {}
        )
        
        self._devices[device_id] = device
        logger.info(f"✅ 设备已注册: {device_id}")
        
        return device
    
    def unregister_device(self, device_id: str) -> bool:
        """
        注销设备
        
        Args:
            device_id: 设备 ID
        
        Returns:
            bool: 是否成功
        """
        if device_id not in self._devices:
            logger.warning(f"⚠️ 设备不存在: {device_id}")
            return False
        
        device = self._devices[device_id]
        
        # 如果设备被分配，先释放
        if device.assigned_user_id:
            self.release_device(device_id)
        
        del self._devices[device_id]
        logger.info(f"✅ 设备已注销: {device_id}")
        
        return True
    
    def get_device(self, device_id: str) -> Optional[VirtualDevice]:
        """获取设备信息"""
        return self._devices.get(device_id)
    
    def get_all_devices(self) -> List[VirtualDevice]:
        """获取所有设备"""
        return list(self._devices.values())
    
    def get_available_devices(self) -> List[VirtualDevice]:
        """获取所有可用设备"""
        return [d for d in self._devices.values() if d.status == DeviceStatus.AVAILABLE]
    
    async def acquire_device(
        self,
        user_id: str,
        preferred_device_id: str = None
    ) -> Optional[VirtualDevice]:
        """
        为用户分配设备
        
        Args:
            user_id: 用户 ID
            preferred_device_id: 首选设备 ID
        
        Returns:
            VirtualDevice: 分配的设备，如果没有可用设备返回 None
        """
        # 检查用户是否已有分配的设备
        if user_id in self._user_device_map:
            device_id = self._user_device_map[user_id]
            device = self._devices.get(device_id)
            if device and device.status == DeviceStatus.BUSY:
                logger.info(f"📱 用户 {user_id} 已有分配的设备: {device_id}")
                return device
        
        # 如果指定了首选设备且可用
        if preferred_device_id:
            device = self._devices.get(preferred_device_id)
            if device and device.status == DeviceStatus.AVAILABLE:
                return self._assign_device(device, user_id)
        
        # 查找可用设备
        available_devices = self.get_available_devices()
        
        if not available_devices:
            logger.warning(f"⚠️ 没有可用设备分配给用户: {user_id}")
            return None
        
        # 分配第一个可用设备
        device = available_devices[0]
        return self._assign_device(device, user_id)
    
    def _assign_device(self, device: VirtualDevice, user_id: str) -> VirtualDevice:
        """分配设备给用户"""
        device.status = DeviceStatus.BUSY
        device.assigned_user_id = user_id
        device.last_activity = datetime.now()
        
        self._user_device_map[user_id] = device.device_id
        
        logger.info(f"📱 设备已分配: {device.device_id} -> 用户 {user_id}")
        
        return device
    
    def release_device(self, device_id: str) -> bool:
        """
        释放设备
        
        Args:
            device_id: 设备 ID
        
        Returns:
            bool: 是否成功
        """
        device = self._devices.get(device_id)
        
        if not device:
            logger.warning(f"⚠️ 设备不存在: {device_id}")
            return False
        
        # 移除用户映射
        if device.assigned_user_id:
            user_id = device.assigned_user_id
            if user_id in self._user_device_map:
                del self._user_device_map[user_id]
            device.assigned_user_id = None
        
        device.status = DeviceStatus.AVAILABLE
        device.last_activity = datetime.now()
        
        logger.info(f"📱 设备已释放: {device_id}")
        
        return True
    
    def get_user_device(self, user_id: str) -> Optional[VirtualDevice]:
        """
        获取用户当前分配的设备
        
        Args:
            user_id: 用户 ID
        
        Returns:
            VirtualDevice: 用户的设备，如果没有返回 None
        """
        device_id = self._user_device_map.get(user_id)
        if device_id:
            return self._devices.get(device_id)
        return None
    
    async def check_device_health(self, device_id: str) -> bool:
        """
        检查设备健康状态
        
        Args:
            device_id: 设备 ID
        
        Returns:
            bool: 设备是否健康
        """
        try:
            process = await asyncio.create_subprocess_exec(
                "adb", "-s", device_id, "shell", "echo", "ping",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5)
            
            if b"ping" in stdout:
                return True
            return False
            
        except Exception as e:
            logger.warning(f"⚠️ 设备健康检查失败: {device_id}, 错误: {e}")
            return False
    
    async def refresh_device_status(self):
        """刷新所有设备状态"""
        logger.info("🔄 刷新设备状态...")
        
        for device in self._devices.values():
            try:
                is_healthy = await self.check_device_health(device.device_id)
                
                if is_healthy:
                    if device.status == DeviceStatus.OFFLINE:
                        device.status = DeviceStatus.AVAILABLE
                        logger.info(f"📱 设备恢复在线: {device.device_id}")
                else:
                    if device.status != DeviceStatus.OFFLINE:
                        device.status = DeviceStatus.OFFLINE
                        logger.warning(f"📱 设备离线: {device.device_id}")
                        
            except Exception as e:
                logger.error(f"❌ 刷新设备状态失败: {device.device_id}, 错误: {e}")
        
        logger.info("✅ 设备状态刷新完成")
    
    def get_status_summary(self) -> Dict[str, Any]:
        """获取设备状态摘要"""
        total = len(self._devices)
        available = len([d for d in self._devices.values() if d.status == DeviceStatus.AVAILABLE])
        busy = len([d for d in self._devices.values() if d.status == DeviceStatus.BUSY])
        offline = len([d for d in self._devices.values() if d.status == DeviceStatus.OFFLINE])
        
        return {
            "total_devices": total,
            "available": available,
            "busy": busy,
            "offline": offline,
            "user_assignments": len(self._user_device_map),
            "devices": [d.to_dict() for d in self._devices.values()]
        }


# 全局设备管理器实例
_device_manager: Optional[DeviceManager] = None


def get_device_manager() -> DeviceManager:
    """获取设备管理器单例"""
    global _device_manager
    
    if _device_manager is None:
        _device_manager = DeviceManager()
    
    return _device_manager


def reset_device_manager():
    """重置设备管理器"""
    global _device_manager
    _device_manager = None
    logger.info("🔄 设备管理器已重置")

