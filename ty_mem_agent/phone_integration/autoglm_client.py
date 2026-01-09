#!/usr/bin/env python3
"""
AutoGLM 客户端封装

封装 Open-AutoGLM 的调用，支持：
1. 命令行调用方式（通过 subprocess）
2. Python API 调用方式（如果 Open-AutoGLM 提供了）

参考：https://github.com/zai-org/Open-AutoGLM
"""

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class PhoneOperationResult:
    """手机操作结果"""
    success: bool
    message: str
    task_id: str = ""
    status: TaskStatus = TaskStatus.PENDING
    screenshots: List[str] = field(default_factory=list)  # 截图路径列表
    steps: List[Dict[str, Any]] = field(default_factory=list)  # 执行步骤
    duration_seconds: float = 0.0
    error: Optional[str] = None
    raw_output: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "task_id": self.task_id,
            "status": self.status.value,
            "screenshots": self.screenshots,
            "steps": self.steps,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
        }


class AutoGLMClient:
    """
    AutoGLM 客户端
    
    封装 Open-AutoGLM 的调用，提供统一的接口
    
    使用方式：
    1. 命令行调用：通过 subprocess 调用 Open-AutoGLM 的 main.py
    2. Python API：如果 Open-AutoGLM 提供了 Python API，可以直接调用
    """
    
    # 支持的 APP 列表（用于任务验证和提示）
    SUPPORTED_APPS = {
        "12306": {
            "name": "12306",
            "package": "com.MobileTicket",
            "operations": ["查询火车票", "预订火车票", "查看订单"],
            "description": "铁路12306官方购票应用"
        },
        "携程": {
            "name": "携程旅行",
            "package": "ctrip.android.view",
            "operations": ["查询机票", "预订机票", "查询酒店", "预订酒店"],
            "description": "携程旅行预订应用"
        },
        "飞猪": {
            "name": "飞猪",
            "package": "com.taobao.trip",
            "operations": ["查询机票", "预订机票", "查询酒店", "预订酒店"],
            "description": "阿里飞猪旅行应用"
        },
        "淘宝": {
            "name": "淘宝",
            "package": "com.taobao.taobao",
            "operations": ["搜索商品", "加入购物车", "查看订单"],
            "description": "淘宝购物应用"
        },
        "京东": {
            "name": "京东",
            "package": "com.jingdong.app.mall",
            "operations": ["搜索商品", "加入购物车", "查看订单"],
            "description": "京东购物应用"
        },
        "拼多多": {
            "name": "拼多多",
            "package": "com.xunmeng.pinduoduo",
            "operations": ["搜索商品", "加入购物车", "查看订单"],
            "description": "拼多多购物应用"
        },
        "美团": {
            "name": "美团",
            "package": "com.sankuai.meituan",
            "operations": ["搜索外卖", "搜索餐厅", "加入购物车"],
            "description": "美团外卖和生活服务"
        },
        "饿了么": {
            "name": "饿了么",
            "package": "me.ele",
            "operations": ["搜索外卖", "加入购物车"],
            "description": "饿了么外卖应用"
        },
        "滴滴": {
            "name": "滴滴出行",
            "package": "com.sdu.didi.psnger",
            "operations": ["预约用车", "叫车", "查看行程"],
            "description": "滴滴出行打车应用"
        },
        "高德": {
            "name": "高德地图",
            "package": "com.autonavi.minimap",
            "operations": ["导航", "搜索地点", "预约打车"],
            "description": "高德地图导航应用"
        },
        "微信": {
            "name": "微信",
            "package": "com.tencent.mm",
            "operations": ["发送消息", "查看消息"],
            "description": "微信社交应用"
        },
    }
    
    def __init__(
        self,
        base_url: str = None,
        model: str = None,
        api_key: str = None,
        autoglm_path: str = None,
        default_device_id: str = None,
        default_timeout: int = 180,
    ):
        """
        初始化 AutoGLM 客户端
        
        Args:
            base_url: 模型服务 URL，如 https://open.bigmodel.cn/api/paas/v4
            model: 模型名称，如 autoglm-phone
            api_key: API Key
            autoglm_path: Open-AutoGLM 项目路径
            default_device_id: 默认设备 ID，如 emulator-5554
            default_timeout: 默认超时时间（秒）
        """
        # 从环境变量或参数获取配置
        self.base_url = base_url or os.getenv("AUTOGLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
        self.model = model or os.getenv("AUTOGLM_MODEL", "autoglm-phone")
        self.api_key = api_key or os.getenv("AUTOGLM_API_KEY", "")
        self.autoglm_path = autoglm_path or os.getenv("AUTOGLM_PATH", "")
        self.default_device_id = default_device_id or os.getenv("AUTOGLM_DEVICE_ID", "emulator-5554")
        self.default_timeout = default_timeout
        
        # 任务计数器
        self._task_counter = 0
        
        # 验证配置
        self._validate_config()
        
        logger.info(f"✅ AutoGLM 客户端初始化完成")
        logger.info(f"   模型服务: {self.base_url}")
        logger.info(f"   模型: {self.model}")
        logger.info(f"   默认设备: {self.default_device_id}")
        if self.autoglm_path:
            logger.info(f"   AutoGLM 路径: {self.autoglm_path}")
    
    def _validate_config(self):
        """验证配置"""
        if not self.api_key:
            logger.warning("⚠️ AUTOGLM_API_KEY 未配置，手机操作功能将不可用")
        
        if self.autoglm_path and not Path(self.autoglm_path).exists():
            logger.warning(f"⚠️ AutoGLM 路径不存在: {self.autoglm_path}")
    
    def _generate_task_id(self) -> str:
        """生成任务 ID"""
        self._task_counter += 1
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"phone_task_{timestamp}_{self._task_counter:04d}"
    
    def is_available(self) -> bool:
        """检查 AutoGLM 是否可用"""
        if not self.api_key:
            return False
        
        # 如果配置了本地路径，检查路径是否存在
        if self.autoglm_path:
            main_py = Path(self.autoglm_path) / "main.py"
            if not main_py.exists():
                logger.warning(f"⚠️ AutoGLM main.py 不存在: {main_py}")
                return False
        
        return True
    
    def get_supported_apps(self) -> Dict[str, Dict[str, Any]]:
        """获取支持的 APP 列表"""
        return self.SUPPORTED_APPS.copy()
    
    def is_app_supported(self, app_name: str) -> bool:
        """检查 APP 是否支持"""
        return app_name in self.SUPPORTED_APPS
    
    async def execute_task(
        self,
        task_description: str,
        device_id: str = None,
        timeout: int = None,
        app_hint: str = None,
    ) -> PhoneOperationResult:
        """
        执行手机操作任务
        
        Args:
            task_description: 任务描述，如 "在12306预订明天从重庆到昆明的高铁票"
            device_id: 设备 ID，如 emulator-5554
            timeout: 超时时间（秒）
            app_hint: APP 提示，如 "12306"
        
        Returns:
            PhoneOperationResult: 操作结果
        """
        task_id = self._generate_task_id()
        device_id = device_id or self.default_device_id
        timeout = timeout or self.default_timeout
        
        logger.info(f"📱 开始执行手机操作任务")
        logger.info(f"   任务ID: {task_id}")
        logger.info(f"   任务描述: {task_description}")
        logger.info(f"   目标设备: {device_id}")
        logger.info(f"   超时时间: {timeout}秒")
        
        # 检查可用性
        if not self.is_available():
            return PhoneOperationResult(
                success=False,
                message="AutoGLM 服务不可用，请检查配置",
                task_id=task_id,
                status=TaskStatus.FAILED,
                error="AutoGLM 服务未配置或不可用"
            )
        
        start_time = datetime.now()
        
        try:
            # 执行任务
            result = await self._execute_via_subprocess(
                task_description=task_description,
                device_id=device_id,
                timeout=timeout,
                task_id=task_id
            )
            
            duration = (datetime.now() - start_time).total_seconds()
            result.duration_seconds = duration
            result.task_id = task_id
            
            if result.success:
                logger.info(f"✅ 任务执行成功: {task_id}, 耗时: {duration:.1f}秒")
            else:
                logger.warning(f"❌ 任务执行失败: {task_id}, 错误: {result.error}")
            
            return result
            
        except asyncio.TimeoutError:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"⏰ 任务超时: {task_id}, 已执行: {duration:.1f}秒")
            return PhoneOperationResult(
                success=False,
                message=f"任务执行超时（{timeout}秒）",
                task_id=task_id,
                status=TaskStatus.TIMEOUT,
                duration_seconds=duration,
                error="任务执行超时"
            )
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"❌ 任务执行异常: {task_id}, 错误: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return PhoneOperationResult(
                success=False,
                message=f"任务执行异常: {str(e)}",
                task_id=task_id,
                status=TaskStatus.FAILED,
                duration_seconds=duration,
                error=str(e)
            )
    
    async def _execute_via_subprocess(
        self,
        task_description: str,
        device_id: str,
        timeout: int,
        task_id: str
    ) -> PhoneOperationResult:
        """
        通过子进程调用 Open-AutoGLM
        
        命令格式：
        python main.py --base-url {URL} --model {MODEL} --apikey {KEY} "{TASK}"
        """
        if not self.autoglm_path:
            # 如果没有配置本地路径，使用模拟模式
            return await self._execute_mock(task_description, task_id)
        
        # 构建命令
        cmd = [
            sys.executable,  # 使用当前 Python 解释器
            "main.py",
            "--base-url", self.base_url,
            "--model", self.model,
            "--apikey", self.api_key,
        ]
        
        # 如果支持设备参数
        # cmd.extend(["--device", device_id])
        
        # 添加任务描述
        cmd.append(task_description)
        
        logger.debug(f"执行命令: {' '.join(cmd[:6])}... '{task_description[:50]}...'")
        
        try:
            # 异步执行子进程
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.autoglm_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "PYTHONUNBUFFERED": "1"}
            )
            
            # 等待执行完成
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
            
            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")
            
            # 解析结果
            if process.returncode == 0:
                return PhoneOperationResult(
                    success=True,
                    message="任务执行成功",
                    task_id=task_id,
                    status=TaskStatus.SUCCESS,
                    raw_output=stdout_text,
                    steps=self._parse_steps_from_output(stdout_text)
                )
            else:
                return PhoneOperationResult(
                    success=False,
                    message="任务执行失败",
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    raw_output=stdout_text,
                    error=stderr_text or "执行返回非零状态码"
                )
                
        except asyncio.TimeoutError:
            # 超时处理
            if process:
                process.kill()
            raise
    
    async def _execute_mock(
        self,
        task_description: str,
        task_id: str
    ) -> PhoneOperationResult:
        """
        模拟执行（用于测试或演示）
        
        当 AutoGLM 路径未配置时，返回模拟结果
        """
        logger.info(f"🎭 使用模拟模式执行任务: {task_description[:50]}...")
        
        # 模拟执行延迟
        await asyncio.sleep(2)
        
        # 根据任务描述生成模拟结果
        mock_steps = [
            {"step": 1, "action": "启动应用", "status": "completed"},
            {"step": 2, "action": "搜索相关内容", "status": "completed"},
            {"step": 3, "action": "选择目标项目", "status": "completed"},
            {"step": 4, "action": "添加到购物车/订单", "status": "completed"},
        ]
        
        return PhoneOperationResult(
            success=True,
            message=f"[模拟模式] 任务已完成: {task_description[:30]}...\n请在您的真实手机上确认并完成支付。",
            task_id=task_id,
            status=TaskStatus.SUCCESS,
            steps=mock_steps,
            raw_output="[MOCK MODE] Task simulated successfully"
        )
    
    def _parse_steps_from_output(self, output: str) -> List[Dict[str, Any]]:
        """从输出中解析执行步骤"""
        steps = []
        
        # 尝试解析 AutoGLM 的输出格式
        # 这里需要根据实际的 AutoGLM 输出格式进行调整
        lines = output.split("\n")
        step_num = 0
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # 尝试匹配步骤信息
            if "Action:" in line or "click" in line.lower() or "tap" in line.lower():
                step_num += 1
                steps.append({
                    "step": step_num,
                    "action": line,
                    "status": "completed"
                })
        
        return steps
    
    async def check_device_connection(self, device_id: str = None) -> bool:
        """
        检查设备连接状态
        
        Args:
            device_id: 设备 ID
        
        Returns:
            bool: 设备是否已连接
        """
        device_id = device_id or self.default_device_id
        
        try:
            process = await asyncio.create_subprocess_exec(
                "adb", "devices",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            output = stdout.decode("utf-8")
            
            # 检查设备是否在列表中
            if device_id in output and "device" in output:
                logger.info(f"✅ 设备已连接: {device_id}")
                return True
            else:
                logger.warning(f"⚠️ 设备未连接: {device_id}")
                return False
                
        except Exception as e:
            logger.error(f"❌ 检查设备连接失败: {e}")
            return False
    
    async def get_device_screenshot(self, device_id: str = None) -> Optional[str]:
        """
        获取设备截图
        
        Args:
            device_id: 设备 ID
        
        Returns:
            str: 截图文件路径，失败返回 None
        """
        device_id = device_id or self.default_device_id
        
        try:
            # 创建截图保存目录
            screenshot_dir = Path("data/phone_screenshots")
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            
            # 生成截图文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = screenshot_dir / f"screenshot_{device_id}_{timestamp}.png"
            
            # 在设备上截图
            await asyncio.create_subprocess_exec(
                "adb", "-s", device_id, "shell", "screencap", "-p", "/sdcard/screenshot.png"
            )
            
            # 拉取截图到本地
            process = await asyncio.create_subprocess_exec(
                "adb", "-s", device_id, "pull", "/sdcard/screenshot.png", str(screenshot_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
            
            if screenshot_path.exists():
                logger.info(f"📸 截图已保存: {screenshot_path}")
                return str(screenshot_path)
            else:
                logger.warning("⚠️ 截图保存失败")
                return None
                
        except Exception as e:
            logger.error(f"❌ 获取截图失败: {e}")
            return None


# 全局客户端实例
_autoglm_client: Optional[AutoGLMClient] = None


def get_autoglm_client() -> AutoGLMClient:
    """获取 AutoGLM 客户端单例"""
    global _autoglm_client
    
    if _autoglm_client is None:
        _autoglm_client = AutoGLMClient()
    
    return _autoglm_client


def reset_autoglm_client():
    """重置客户端（用于配置更新后重新初始化）"""
    global _autoglm_client
    _autoglm_client = None
    logger.info("🔄 AutoGLM 客户端已重置")

