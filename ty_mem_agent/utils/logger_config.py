#!/usr/bin/env python3
"""
统一日志配置模块
提供项目级别的日志配置和管理
"""

import sys
import os
from pathlib import Path
from typing import Optional
from loguru import logger


class LoggerConfig:
    """日志配置管理器"""
    
    _initialized = False
    _loggers = {}
    
    @classmethod
    def setup_logger(cls, 
                    name: str = "TYMemoryAgent",
                    level: str = "INFO",
                    log_file: Optional[str] = None,
                    rotation: str = "10 MB",
                    retention: str = "7 days",
                    format_string: Optional[str] = None) -> None:
        """
        设置全局日志配置
        
        Args:
            name: 日志器名称
            level: 日志级别
            log_file: 日志文件路径  
            rotation: 日志轮转大小
            retention: 日志保留时间
            format_string: 自定义格式字符串
        """
        # 允许重复配置：每次调用都重置处理器，应用新的级别/格式/文件
        if cls._initialized:
            logger.remove()
            
        # 移除默认处理器
        logger.remove()
        
        # 控制台日志格式
        console_format = (
            "<green>{time:MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan> | "
            "<level>{message}</level>"
        )
        
        if format_string:
            console_format = format_string
        
        # 添加控制台处理器
        logger.add(
            sys.stdout,
            level=level,
            format=console_format,
            colorize=True,
            filter=lambda record: record["level"].name != "TRACE"
        )
        
        # 添加文件处理器（如果指定了文件路径）
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            file_format = (
                "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
                "{level: <8} | "
                "{name}:{function}:{line} | "
                "{message}"
            )
            
            logger.add(
                log_file,
                level=level,
                format=file_format,
                rotation=rotation,
                retention=retention,
                compression="zip",
                encoding="utf-8"
            )
        
        cls._initialized = True
        logger.info(f"📋 日志系统初始化完成 - Level: {level}")
    
    @classmethod
    def get_logger(cls, name: str = None) -> "logger":
        """
        获取指定名称的日志器
        
        Args:
            name: 日志器名称，如果为None则返回默认logger
            
        Returns:
            配置好的logger实例
        """
        if not cls._initialized:
            # 如果未初始化，使用环境变量驱动的默认配置
            init_default_logging()
        
        if name is None:
            return logger
            
        # 创建带上下文的logger
        if name not in cls._loggers:
            cls._loggers[name] = logger.bind(name=name)
        
        return cls._loggers[name]
    
    @classmethod
    def set_level(cls, level: str) -> None:
        """动态设置日志级别"""
        # 移除现有处理器并重新配置
        cls._initialized = False
        cls.setup_logger(level=level)
    
    @classmethod
    def add_file_handler(cls, 
                        file_path: str,
                        level: str = "DEBUG",
                        rotation: str = "100 MB") -> None:
        """添加额外的文件处理器"""
        log_path = Path(file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.add(
            file_path,
            level=level,
            rotation=rotation,
            retention="30 days",
            compression="zip",
            format="{time} | {level} | {name}:{function}:{line} | {message}"
        )
        
        logger.info(f"📁 添加文件日志处理器: {file_path}")


# 便捷函数
def setup_logger(name: str = "TYMemoryAgent", 
                level: str = "INFO",
                log_file: Optional[str] = None,
                **kwargs) -> None:
    """设置日志系统"""
    LoggerConfig.setup_logger(name, level, log_file, **kwargs)


def get_logger(name: str = None) -> "logger":
    """获取logger实例"""
    return LoggerConfig.get_logger(name)


# 模块级logger实例将在底部初始化，避免初始化顺序问题


# 为不同模块提供专用logger
def get_agent_logger():
    """获取Agent模块logger"""
    return get_logger("Agent")


def get_memory_logger():
    """获取Memory模块logger"""
    return get_logger("Memory")


def get_mcp_logger():
    """获取MCP模块logger"""
    return get_logger("MCP")


def get_server_logger():
    """获取Server模块logger"""
    return get_logger("Server")


def get_config_logger():
    """获取Config模块logger"""
    return get_logger("Config")


# 日志装饰器
def log_execution_time(func_name: str = None):
    """记录函数执行时间的装饰器"""
    def decorator(func):
        import time
        import functools
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            name = func_name or f"{func.__module__}.{func.__name__}"
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time
                get_logger().debug(f"⏱️ {name} 执行时间: {execution_time:.3f}s")
                return result
            except Exception as e:
                execution_time = time.time() - start_time
                get_logger().error(f"❌ {name} 执行失败 ({execution_time:.3f}s): {e}")
                raise
        
        return wrapper
    return decorator


def log_async_execution_time(func_name: str = None):
    """记录异步函数执行时间的装饰器"""
    def decorator(func):
        import time
        import functools
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            name = func_name or f"{func.__module__}.{func.__name__}"
            start_time = time.time()
            
            try:
                result = await func(*args, **kwargs)
                execution_time = time.time() - start_time
                get_logger().debug(f"⏱️ {name} 执行时间: {execution_time:.3f}s")
                return result
            except Exception as e:
                execution_time = time.time() - start_time
                get_logger().error(f"❌ {name} 执行失败 ({execution_time:.3f}s): {e}")
                raise
        
        return wrapper
    return decorator


# 上下文管理器
class LogContext:
    """日志上下文管理器"""
    
    def __init__(self, operation: str, logger_instance=None):
        self.operation = operation
        self.logger = logger_instance or get_logger()
        self.start_time = None
    
    def __enter__(self):
        self.start_time = __import__('time').time()
        self.logger.info(f"🚀 开始: {self.operation}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        execution_time = __import__('time').time() - self.start_time
        
        if exc_type is None:
            self.logger.info(f"✅ 完成: {self.operation} ({execution_time:.3f}s)")
        else:
            self.logger.error(f"❌ 失败: {self.operation} ({execution_time:.3f}s) - {exc_val}")
        
        return False  # 不抑制异常


# 初始化默认配置
def init_default_logging():
    """初始化默认日志配置"""
    # 使用 settings 中的统一配置来源（pydantic 会从 .env 加载）
    try:
        from ty_mem_agent.config.settings import settings
        log_level = settings.LOG_LEVEL or 'INFO'
        log_file = settings.LOG_FILE or 'logs/ty_mem_agent.log'
    except Exception:
        # 兜底：环境变量或默认
        log_level = os.getenv('LOG_LEVEL', 'INFO')
        log_file = os.getenv('LOG_FILE', 'logs/ty_mem_agent.log')
    
    setup_logger(
        name="TYMemoryAgent",
        level=log_level,
        log_file=log_file
    )


if __name__ == "__main__":
    # 测试日志配置
    setup_logger(level="DEBUG", log_file="test.log")
    
    test_logger = get_logger("TestModule")
    
    test_logger.debug("这是一条调试信息")
    test_logger.info("这是一条信息")
    test_logger.warning("这是一条警告")
    test_logger.error("这是一条错误")
    
    # 测试上下文管理器
    with LogContext("测试操作", test_logger):
        test_logger.info("正在执行测试操作...")
        import time
        time.sleep(0.1)
    
    # 测试装饰器
    @log_execution_time("测试函数")
    def test_function():
        import time
        time.sleep(0.05)
        return "测试结果"
    
    result = test_function()
    test_logger.info(f"函数返回: {result}")

# 在模块导入完成后再初始化模块级 logger，避免引用未定义函数
module_logger = get_logger("TYMemoryAgent")
