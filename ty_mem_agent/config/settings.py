#!/usr/bin/env python3
"""
TY Memory Agent 配置文件
"""

import os
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """系统配置"""
    
    class Config:
        env_file = str(Path(__file__).parent.parent / ".env")
        env_file_encoding = "utf-8"
    
    # === 基础配置 ===
    PROJECT_NAME: str = "TY Memory Agent"
    VERSION: str = "1.0.0"
    DEBUG: bool = Field(default=False, env="DEBUG")
    
    # === 服务器配置 ===
    HOST: str = Field(default="0.0.0.0", env="HOST")
    PORT: int = Field(default=8080, env="PORT")
    
    # CORS 配置
    ALLOWED_ORIGINS: str = Field(default="*", env="ALLOWED_ORIGINS")
    
    # === LLM配置 ===
    # DashScope配置
    DASHSCOPE_API_KEY: Optional[str] = Field(default=None, env="DASHSCOPE_API_KEY")
    DEFAULT_LLM_MODEL: str = Field(default="qwen-max", env="DEFAULT_LLM_MODEL")
    
    # OpenAI配置（备选）
    OPENAI_API_KEY: Optional[str] = Field(default=None, env="OPENAI_API_KEY")
    OPENAI_BASE_URL: str = Field(default="https://api.openai.com/v1", env="OPENAI_BASE_URL")
    
    # === MemOS记忆系统配置 ===
    MEMOS_API_BASE: str = Field(default="https://api.openmem.net", env="MEMOS_API_BASE")
    MEMOS_API_KEY: Optional[str] = Field(default=None, env="MEMOS_API_KEY")
    
    # 记忆配置
    MEMORY_MAX_TOKENS: int = Field(default=4000, env="MEMORY_MAX_TOKENS")
    MEMORY_RETENTION_DAYS: int = Field(default=30, env="MEMORY_RETENTION_DAYS")
    
    # === 数据库配置 ===
    # Redis配置（用户会话）
    REDIS_URL: str = Field(default="redis://localhost:6379/0", env="REDIS_URL")
    
    # SQLite配置（用户数据）
    DATABASE_URL: str = Field(default="sqlite:///./ty_mem_agent.db", env="DATABASE_URL")
    
    # 数据库文件路径配置（将在__init__中动态设置为绝对路径）
    DATA_DIR: str = Field(default="", env="DATA_DIR")
    USER_MEMORY_DB_PATH: str = Field(default="", env="USER_MEMORY_DB_PATH")
    USERS_DB_PATH: str = Field(default="", env="USERS_DB_PATH")
    
    # === 用户认证配置 ===
    SECRET_KEY: str = Field(default="your-secret-key-change-in-production", env="SECRET_KEY")
    # 访问令牌过期时间（30天 = 43200分钟）
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=43200, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    
    # === MCP服务API密钥 ===
    DIDI_API_KEY: Optional[str] = Field(default=None, env="DIDI_API_KEY")
    DIDI_MCP_MODE: str = Field(default="production", env="DIDI_MCP_MODE")  # production 或 sandbox
    AMAP_TOKEN: Optional[str] = Field(default=None, env="AMAP_TOKEN")
    BOCHA_API_KEY: Optional[str] = Field(default=None, env="BOCHA_API_KEY")
    VARIFLIGHT_API_KEY: Optional[str] = Field(default=None, env="VARIFLIGHT_API_KEY")
    
    # === 饿了么外卖API密钥 ===
    ELEME_APP_KEY: Optional[str] = Field(default=None, env="ELEME_APP_KEY")
    ELEME_APP_SECRET: Optional[str] = Field(default=None, env="ELEME_APP_SECRET")
    ELEME_MODE: str = Field(default="sandbox", env="ELEME_MODE")  # sandbox 或 production
    
    # === 飞书会议API密钥 ===
    FEISHU_APP_ID: Optional[str] = Field(default=None, env="FEISHU_APP_ID")
    FEISHU_APP_SECRET: Optional[str] = Field(default=None, env="FEISHU_APP_SECRET")
    
    # === 日历MCP服务配置 ===
    CALENDAR_MCP_SERVER_URL: Optional[str] = Field(default=None, env="CALENDAR_MCP_SERVER_URL")
    
    # === MCP服务配置 ===
    @property
    def MCP_SERVICES(self) -> Dict[str, Dict]:
        """动态生成MCP服务配置，包含实际的API密钥"""
        return {
            "didi_ride": {
                "enabled": True,
                "api_key": self.DIDI_API_KEY,
                "mode": self.DIDI_MCP_MODE,
                "description": "滴滴叫车服务"
            },
            "amap_weather": {
                "enabled": True,
                "api_key": self.AMAP_TOKEN,
                "description": "高德天气查询"
            },
            "time": {
                "enabled": True,
                "command": "uvx",
                "args": ["mcp-server-time", "--local-timezone=Asia/Shanghai"],
                "description": "时间查询服务"
            },
            "filesystem": {
                "enabled": False,
                "command": "npx", 
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "~/Documents/"],
                "description": "文件系统操作"
            },
            "bocha_search": {
                "enabled": True,
                "api_key": self.BOCHA_API_KEY,
                "description": "博查AI搜索引擎"
            },
            "variflight": {
                "enabled": True,
                "api_key": self.VARIFLIGHT_API_KEY,
                "description": "飞常准航班信息查询服务"
            },
            "railway_12306": {
                "enabled": True,
                "command": "npx",
                "args": ["-y", "12306-mcp"],
                "description": "12306铁路票务查询服务"
            },
            "stock": {
                "enabled": True,
                "api_key": self.DASHSCOPE_API_KEY,
                "description": "股票查询服务（阿里云百炼）"
            },
            "eleme": {
                "enabled": False,
                "app_key": self.ELEME_APP_KEY,
                "app_secret": self.ELEME_APP_SECRET,
                "mode": self.ELEME_MODE,
                "description": "饿了么外卖服务"
            }
        }
    
    # === Agent配置 ===
    # Agent 主动性级别
    AGENT_PROACTIVITY_LEVEL: str = Field(default="proactive", env="AGENT_PROACTIVITY_LEVEL")
    
    AGENT_CONFIG: Dict = {
        "max_memory_context": 10,  # 最大记忆上下文轮数
        "enable_proactive_memory": True,  # 启用主动记忆
        "memory_update_threshold": 3,  # 记忆更新阈值
        "mcp_selection_strategy": "auto",  # MCP选择策略: auto/manual/router
    }
    
    # === 聊天配置 ===
    CHAT_CONFIG: Dict = {
        "max_message_length": 2000,
        "session_timeout_minutes": 60,
        "enable_message_history": True,
        "max_history_messages": 50
    }
    
    # === 日志配置 ===
    LOG_LEVEL: str = Field(default="INFO", env="LOG_LEVEL")
    LOG_FILE: str = Field(default="ty_mem_agent/logs/ty_mem_agent.log", env="LOG_FILE")
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 动态设置数据库路径为绝对路径
        self._setup_database_paths()
    
    def _setup_database_paths(self):
        """设置数据库路径为绝对路径"""
        import os
        from pathlib import Path
        
        # 获取项目根目录（ty_mem_agent的父目录）
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent  # 从config/settings.py -> ty_mem_agent -> 项目根目录
        
        # 设置数据目录
        if not self.DATA_DIR:
            self.DATA_DIR = str(project_root / "ty_mem_agent" / "data")
        
        # 设置数据库文件路径
        if not self.USER_MEMORY_DB_PATH:
            self.USER_MEMORY_DB_PATH = str(project_root / "ty_mem_agent" / "data" / "user_memory.db")
        
        if not self.USERS_DB_PATH:
            self.USERS_DB_PATH = str(project_root / "ty_mem_agent" / "data" / "users.db")
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# 全局设置实例
settings = Settings()


def get_llm_config() -> Dict:
    """获取LLM配置"""
    if settings.DASHSCOPE_API_KEY:
        return {
            'model': settings.DEFAULT_LLM_MODEL,
            'model_type': 'qwen_dashscope',
            'api_key': settings.DASHSCOPE_API_KEY,
        }
    elif settings.OPENAI_API_KEY:
        return {
            'model': 'gpt-4o-mini',
            'model_server': settings.OPENAI_BASE_URL,
            'api_key': settings.OPENAI_API_KEY,
        }
    else:
        raise ValueError("需要配置 DASHSCOPE_API_KEY 或 OPENAI_API_KEY")


def get_available_mcp_services() -> List[str]:
    """获取可用的MCP服务列表"""
    available = []
    for service_name, config in settings.MCP_SERVICES.items():
        if config.get("enabled", False):
            # 检查API密钥是否配置
            api_key = config.get("api_key")
            if api_key is None:
                continue
            available.append(service_name)
    return available


def validate_configuration():
    """验证配置是否完整"""
    errors = []
    
    # 检查必要的API密钥
    if not settings.DASHSCOPE_API_KEY and not settings.OPENAI_API_KEY:
        errors.append("需要配置 DASHSCOPE_API_KEY 或 OPENAI_API_KEY")
    
    # 检查MemOS配置
    if not settings.MEMOS_API_KEY:
        errors.append("需要配置 MEMOS_API_KEY 以使用记忆系统")
    
    # 检查MCP服务
    available_services = get_available_mcp_services()
    if not available_services:
        errors.append("没有可用的MCP服务，请检查相关API密钥配置")
    
    if errors:
        raise ValueError(f"配置验证失败: {'; '.join(errors)}")
    
    return True


if __name__ == "__main__":
    # 测试配置
    from ty_mem_agent.utils.logger_config import get_logger
    test_logger = get_logger("ConfigTest")
    
    try:
        validate_configuration()
        test_logger.info("✅ 配置验证通过")
        test_logger.info(f"🤖 LLM配置: {get_llm_config()}")
        test_logger.info(f"🔧 可用MCP服务: {get_available_mcp_services()}")
    except Exception as e:
        test_logger.error(f"❌ 配置错误: {e}")
