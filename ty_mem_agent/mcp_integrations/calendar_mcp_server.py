#!/usr/bin/env python3
"""
Calendar MCP Server 配置
日历事件管理服务
提供一次性事件和重复事件的增删改查功能
使用 Streamable HTTP Endpoint 方式集成
"""

import os
import json
from typing import Dict, Optional, List, Any
from datetime import datetime, timedelta
from qwen_agent.tools.base import BaseTool
from ty_mem_agent.utils.logger_config import get_logger

logger = get_logger("CalendarMCPServer")


def get_calendar_mcp_server_config() -> Dict:
    """
    获取日历 MCP Server 配置
    
    Returns:
        MCP Server 配置字典，用于 QwenAgent MCPManager
    """
    # 日历MCP服务器地址（支持环境变量配置）
    # 优先级：
    # 1. CALENDAR_MCP_SERVER_URL 环境变量（推荐，支持本地/远程任意地址）
    # 2. 自动检测网络环境
    
    calendar_server_url = os.environ.get('CALENDAR_MCP_SERVER_URL')
    
    if calendar_server_url:
        logger.info(f"📍 使用配置的日历 MCP 地址: {calendar_server_url}")
    else:
        # 检测是否在 Docker 容器中
        in_docker = os.path.exists('/.dockerenv') or os.environ.get('DOCKER_CONTAINER') == 'true'
        
        if in_docker:
            # Docker 环境：检测网络模式
            # 1. 尝试解析 host.docker.internal（标准端口映射模式）
            # 2. 如果失败，使用 localhost（host 网络模式）
            import socket
            try:
                socket.gethostbyname('host.docker.internal')
                # 标准端口映射模式：通过 host.docker.internal 访问宿主机
                calendar_server_url = 'http://host.docker.internal:18091/mcp'
                logger.info("🐳 检测到 Docker 标准网络模式，使用 host.docker.internal 访问日历服务")
            except socket.gaierror:
                # Host 网络模式：直接通过 localhost 访问
                calendar_server_url = 'http://localhost:18091/mcp'
                logger.info("🐳 检测到 Docker Host 网络模式，使用 localhost 访问日历服务")
        else:
            # 研发机环境：使用远程 IP 地址
            calendar_server_url = 'http://10.1.115.38:18091/mcp'
            logger.info("💻 检测到研发机环境，使用 IP 地址访问日历服务")
    
    config = {
        "mcpServers": {
            "calendar-service": {
                "type": "streamable-http",
                "url": calendar_server_url,
                "sse_read_timeout": 300,
                "headers": {
                    "Accept": "text/event-stream"
                }
            }
        }
    }
    
    logger.info("✅ 日历 MCP Server 配置已生成")
    logger.info(f"   Server URL: {calendar_server_url}")
    logger.info(f"   Connection Type: Streamable HTTP")
    
    return config


class CalendarMCPServerManager:
    """日历 MCP Server 管理器"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CalendarMCPServerManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.mcp_manager = None
            self.tools: List[BaseTool] = []
            self.original_tools: List[BaseTool] = []
            self._initialized = True
    
    def initialize(self) -> None:
        """初始化日历 MCP Server 连接"""
        # 如果已经初始化过，不重复初始化
        if self.tools:
            logger.debug(f"✅ 日历 MCP Server 已初始化，跳过重复初始化")
            return
        
        try:
            from qwen_agent.tools.mcp_manager import MCPManager
        except ImportError as e:
            logger.error("❌ 无法导入 MCPManager，请安装 mcp: pip install -U mcp")
            raise ImportError("需要安装 mcp: pip install -U mcp") from e
        
        # 获取配置
        mcp_config = get_calendar_mcp_server_config()
        
        # 初始化 MCP Manager
        logger.info("📅 正在连接日历 MCP Server...")
        self.mcp_manager = MCPManager()
        
        try:
            # 初始化 MCP 连接并获取工具
            self.original_tools = self.mcp_manager.initConfig(mcp_config)
            
            if self.original_tools:
                # 包装工具以添加日志记录
                from ty_mem_agent.mcp_integrations.tool_wrapper import LoggingToolWrapper
                self.tools = []
                for tool in self.original_tools:
                    wrapped_tool = LoggingToolWrapper(tool)
                    self.tools.append(wrapped_tool)
                
                logger.info(f"✅ 日历 MCP Server 连接成功，获取到 {len(self.tools)} 个工具")
                
                # 记录可用工具
                for tool in self.tools:
                    logger.info(f"   📋 工具: {tool.name} - {getattr(tool, 'description', '无描述')}")
                    
            else:
                logger.warning("⚠️ 日历 MCP Server 连接成功，但未获取到工具")
                
        except Exception as e:
            logger.error(f"❌ 日历 MCP Server 连接失败: {e}")
            raise e
    
    def get_tools(self) -> List[BaseTool]:
        """获取日历工具列表"""
        if not self.tools:
            self.initialize()
        return self.tools
    
    def cleanup(self):
        """清理资源"""
        if self.mcp_manager:
            try:
                self.mcp_manager.shutdown()
                logger.info("✅ 日历 MCP Server 已关闭")
            except Exception as e:
                logger.warning(f"⚠️ 关闭日历 MCP Server 时出错: {e}")
        
        self.tools = []
        self.original_tools = []


# 全局实例
_calendar_manager = None


def get_calendar_mcp_manager() -> CalendarMCPServerManager:
    """获取日历 MCP Manager 实例"""
    global _calendar_manager
    if _calendar_manager is None:
        _calendar_manager = CalendarMCPServerManager()
    return _calendar_manager


def register_calendar_tools() -> List[BaseTool]:
    """
    注册日历工具
    
    Returns:
        日历工具列表
    """
    manager = get_calendar_mcp_manager()
    manager.initialize()
    return manager.get_tools()


def shutdown_calendar_mcp():
    """关闭日历 MCP 连接"""
    global _calendar_manager
    if _calendar_manager:
        _calendar_manager.cleanup()
        _calendar_manager = None
        logger.info("✅ 日历 MCP 连接已关闭")


class CalendarEventManager:
    """日历事件管理器 - 封装日历MCP工具调用"""
    
    def __init__(self, user_id: int):
        """
        初始化日历事件管理器
        
        Args:
            user_id: 整数格式的用户ID（calendar_user_id）
        """
        self.user_id = user_id
        self.manager = get_calendar_mcp_manager()
        self.manager.initialize()
        
        # 获取客户端
        self.client_id = None
        self.client = None
        self._tool_name_map = {}  # 工具名称映射：基础名称 -> 完整名称
        self._init_client()
        self._init_tool_name_map()
    
    def _init_client(self):
        """初始化MCP客户端，查找日历 MCP 客户端"""
        if not self.manager.mcp_manager or not self.manager.mcp_manager.clients:
            logger.error("❌ MCP Manager 或客户端列表不存在")
            return
        
        # 打印所有客户端 ID，方便调试
        all_client_ids = list(self.manager.mcp_manager.clients.keys())
        logger.debug(f"📋 所有可用的 MCP 客户端: {all_client_ids}")
        
        # 查找日历 MCP 客户端
        # 从 mcp_config.json 看，日历 MCP 的 server_name 是 "calendar-service"
        # 客户端 ID 格式可能是 "calendar-service-<timestamp>" 或包含 "calendar" 关键字
        for client_id, client in self.manager.mcp_manager.clients.items():
            # 检查客户端 ID 是否包含 "calendar"
            if "calendar" in client_id.lower():
                self.client_id = client_id
                self.client = client
                logger.info(f"✅ 找到日历 MCP 客户端: {client_id}")
                
                # 打印客户端的工具列表（用于验证）
                if hasattr(client, 'tools') and client.tools:
                    tool_names = [tool.name for tool in client.tools[:3]]  # 只显示前3个
                    logger.debug(f"   客户端工具列表（前3个）: {tool_names}")
                return
        
        # 如果没找到日历客户端，报错（不要使用备用方案，因为会导致工具映射错误）
        logger.error(f"❌ 未找到日历 MCP 客户端！可用的客户端: {all_client_ids}")
        logger.error("   请确保日历 MCP 服务器已启动，并且在 mcp_config.json 中正确配置")
        raise RuntimeError("未找到日历 MCP 客户端")
    
    def _init_tool_name_map(self):
        """初始化工具名称映射
        
        从日历 MCP 客户端的工具列表中提取工具名称，建立基础名称到MCP服务器原始工具名称的映射
        
        注意：
        - client.tools 中的 tool.name 是 MCP 服务器返回的原始工具名称（不带前缀）
        - 例如：createOneTimeEvent, cancelOneTimeEventInstance
        - execute_function 需要这些原始工具名称
        """
        if not self.client_id or not self.manager.mcp_manager:
            logger.warning("⚠️ 无法初始化工具名称映射：客户端未初始化")
            return
        
        client = self.manager.mcp_manager.clients.get(self.client_id)
        if not client:
            logger.warning(f"⚠️ 无法找到客户端: {self.client_id}")
            return
        
        if not hasattr(client, 'tools') or not client.tools:
            logger.warning(f"⚠️ 客户端没有工具列表: {self.client_id}")
            return
        
        # 从日历 MCP 客户端的 tools 列表中获取原始工具名称
        logger.debug(f"📋 开始建立工具名称映射，客户端: {self.client_id}")
        for mcp_tool in client.tools:
            # mcp_tool.name 是 MCP 服务器返回的原始工具名称
            # 例如：createOneTimeEvent（不带前缀）
            tool_name = mcp_tool.name
            # 建立映射：基础名称 -> MCP服务器原始工具名称
            self._tool_name_map[tool_name] = tool_name
            logger.debug(f"   📋 工具映射: {tool_name} -> {tool_name}")
        
        logger.info(f"✅ 已建立 {len(self._tool_name_map)} 个日历工具的名称映射")
        
        # 如果没有从客户端获取到任何工具，尝试从注册的工具名称中提取（备用方案）
        if not self._tool_name_map and self.manager.original_tools:
            logger.warning("⚠️ 从客户端未获取到工具，尝试从注册工具中提取（备用方案）")
            for tool in self.manager.original_tools:
                # 工具注册名称格式：calendar-service-createOneTimeEvent
                # 提取基础名称：createOneTimeEvent
                if tool.name.startswith("calendar-service-"):
                    base_name = tool.name.replace("calendar-service-", "")
                    # 假设 MCP 服务器返回的原始工具名称就是基础名称（不带前缀）
                    self._tool_name_map[base_name] = base_name
                    logger.debug(f"   📋 工具映射（备用）: {base_name} -> {base_name}")
            logger.info(f"✅ 已建立 {len(self._tool_name_map)} 个日历工具的名称映射（备用方案）")
    
    def _call_tool(self, tool_name: str, params: Dict) -> str:
        """调用MCP工具
        
        Args:
            tool_name: 工具基础名称（如 'createOneTimeEvent'）
            params: 工具参数
        """
        if not self.client:
            raise RuntimeError("MCP客户端未初始化")
        
        # 从映射中获取 MCP 服务器原始工具名称
        # 如果映射中没有，假设传入的就是 MCP 服务器原始工具名称
        actual_tool_name = self._tool_name_map.get(tool_name, tool_name)
        
        # 构建参数（需要arg0包装）
        tool_args = {"arg0": params}
        
        logger.debug(f"🔧 调用MCP工具: {tool_name} -> {actual_tool_name}")
        logger.debug(f"   参数: {json.dumps(params, ensure_ascii=False)[:200]}...")
        
        # 调用工具（增加超时时间，因为会议事件的metadata较复杂）
        import asyncio
        timeout = 60  # 增加到60秒，处理复杂metadata
        future = asyncio.run_coroutine_threadsafe(
            self.client.execute_function(actual_tool_name, tool_args),
            self.manager.mcp_manager.loop
        )
        try:
            result = future.result(timeout=timeout)
            logger.debug(f"✅ MCP工具调用成功: {actual_tool_name}")
            return result
        except asyncio.TimeoutError:
            logger.error(f"❌ MCP工具调用超时({timeout}秒): {actual_tool_name}")
            # 打印完整参数（不截断），方便排查问题
            logger.error(f"   完整参数: {json.dumps(params, ensure_ascii=False)}")
            raise TimeoutError(f"MCP工具调用超时({timeout}秒): {actual_tool_name}")
        except Exception as e:
            logger.error(f"❌ MCP工具调用失败: {actual_tool_name}, 错误: {e}")
            logger.error(f"   完整参数: {json.dumps(params, ensure_ascii=False)}")
            import traceback
            logger.error(f"   错误堆栈: {traceback.format_exc()}")
            raise
    
    def create_one_time_event(
        self,
        title: str,
        duration: Optional[int] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        timezone: str = "Asia/Shanghai",
        event_date_time: Optional[str] = None
    ) -> str:
        """创建一次性事件
        
        Args:
            title: 事件标题
            duration: 持续时间（秒）
            description: 事件描述
            location: 事件位置
            timezone: 时区
            event_date_time: 事件日期时间（ISO8601格式字符串，如 '2024-01-01' 或 '2024-01-01T12:00:00'）
        """
        params = {
            "title": title,
            "userId": self.user_id,
            "timezone": timezone
        }
        
        if description:
            params["description"] = description
        if location:
            params["location"] = location
        
        if event_date_time:
            params["eventDateTime"] = event_date_time
        
        if duration is not None:
            params["duration"] = duration
        
        return self._call_tool("createOneTimeEvent", params)
    
    def create_recurring_event(
        self,
        title: str,
        rrule: str,
        duration: int,
        event_date_time: Optional[str] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        timezone: str = "Asia/Shanghai"
    ) -> str:
        """创建重复事件
        
        Args:
            title: 事件标题
            rrule: 重复规则（RFC5545格式）
            duration: 持续时间（秒）
            event_date_time: 事件日期时间（ISO8601格式字符串，如 '2024-01-01' 或 '2024-01-01T12:00:00'）
            description: 事件描述
            location: 事件位置
            timezone: 时区
        """
        params = {
            "title": title,
            "userId": self.user_id,
            "timezone": timezone,
            "rrule": rrule,
            "duration": duration
        }
        
        if description:
            params["description"] = description
        if location:
            params["location"] = location
        
        if event_date_time:
            params["eventDateTime"] = event_date_time
        
        return self._call_tool("createRecurringEvent", params)
    
    def query_events(
        self,
        timezone: str = "Asia/Shanghai",
        range_start: Optional[str] = None,
        range_end: Optional[str] = None
    ) -> str:
        """查询事件
        
        Args:
            timezone: 时区
            range_start: 查询开始时间（RFC3339格式，如 '2024-01-01T00:00:00+08:00'）
            range_end: 查询结束时间（RFC3339格式，如 '2024-01-31T23:59:59+08:00'）
        """
        params = {
            "userId": self.user_id,
            "timezone": timezone
        }
        
        # 如果没有提供时间范围，设置默认范围（从30天前到60天后）
        if not range_start or not range_end:
            from datetime import datetime, timedelta
            now = datetime.now()
            if not range_start:
                # 默认从30天前开始查询
                range_start = (now - timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%S+08:00')
            if not range_end:
                # 默认到60天后结束查询
                range_end = (now + timedelta(days=60)).strftime('%Y-%m-%dT%H:%M:%S+08:00')
            logger.debug(f"📅 使用默认时间范围: {range_start} 到 {range_end}")
        
        # 确保时间格式包含时区信息（RFC3339格式）
        if range_start and not ('+' in range_start or 'Z' in range_start or range_start.endswith('+08:00')):
            # 如果没有时区信息，添加 +08:00（中国时区）
            if not range_start.endswith('+08:00'):
                range_start = range_start + '+08:00'
        
        if range_end and not ('+' in range_end or 'Z' in range_end or range_end.endswith('+08:00')):
            if not range_end.endswith('+08:00'):
                range_end = range_end + '+08:00'
        
        params["rangeStart"] = range_start
        params["rangeEnd"] = range_end
        
        logger.debug(f"📅 查询事件时间范围: {range_start} 到 {range_end}")
        
        return self._call_tool("queryAllEventInstances", params)
    
    def cancel_one_time_event(self, event_id: int) -> str:
        """取消一次性事件"""
        params = {
            "eventId": event_id,
            "userId": self.user_id
        }
        return self._call_tool("cancelOneTimeEventInstance", params)
    
    def cancel_recurring_event(self, event_id: int, instance_timestamp: int) -> str:
        """取消重复事件的单个实例"""
        params = {
            "eventId": event_id,
            "userId": self.user_id,
            "instanceTimestamp": instance_timestamp
        }
        return self._call_tool("cancelRecurringEventInstance", params)
    
    def modify_one_time_event_content(
        self,
        event_id: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        timezone: str = "Asia/Shanghai"
    ) -> str:
        """修改一次性事件内容"""
        params = {
            "eventId": event_id,
            "userId": self.user_id,
            "timezone": timezone
        }
        
        if title:
            params["title"] = title
        if description:
            params["description"] = description
        
        return self._call_tool("modifyOneTimeEventInstanceContent", params)
    
    def modify_one_time_event_location(
        self,
        event_id: int,
        location: Optional[str] = None,
        timezone: str = "Asia/Shanghai"
    ) -> str:
        """修改一次性事件位置"""
        params = {
            "eventId": event_id,
            "userId": self.user_id,
            "timezone": timezone
        }
        
        if location:
            params["location"] = location
        
        return self._call_tool("modifyOneTimeEventInstanceLocation", params)
    
    def modify_one_time_event_time(
        self,
        event_id: int,
        event_date_time: Optional[str] = None,
        duration: Optional[int] = None,
        timezone: str = "Asia/Shanghai"
    ) -> str:
        """修改一次性事件时间
        
        Args:
            event_id: 事件ID
            event_date_time: 事件日期时间（ISO8601格式字符串，如 '2024-01-01' 或 '2024-01-01T12:00:00'）
            duration: 持续时间（秒）
            timezone: 时区
        """
        params = {
            "eventId": event_id,
            "userId": self.user_id,
            "timezone": timezone
        }
        
        # eventDateTime 使用 ISO8601 格式字符串
        if event_date_time:
            params["eventDateTime"] = event_date_time
        # duration 仍然是 integer
        if duration is not None:
            params["duration"] = duration
        
        return self._call_tool("modifyOneTimeEventInstanceTime", params)
    
    # 会议相关辅助方法
    def create_meeting_event(
        self,
        topic: str,
        start_time: int,
        end_time: int,
        meeting_url: str,
        participant_names: List[str] = None,
        reserve_id: str = None,
        event_id: str = None,
        calendar_id: str = None,
        location: str = "线上会议",
        timezone: str = "Asia/Shanghai"
    ) -> str:
        """创建会议事件（在日历中添加）
        
        将会议相关信息存储在description的JSON中
        """
        # 构建会议metadata（简化版本，避免MCP服务超时）
        # 新格式：使用简短的压缩格式而不是完整JSON
        # 格式：[M:reserve_id:event_id:calendar_id]
        metadata_compact = f"[M:{reserve_id or ''}:{event_id or ''}:{calendar_id or ''}]"
        
        # 构建描述（简化，减少数据量）
        description_parts = []
        if meeting_url:
            # 限制URL长度，避免超长字符串
            description_parts.append(f"会议链接: {meeting_url[:100]}")
        if participant_names and len(participant_names) <= 5:
            # 限制参会人数量，避免数据过大
            description_parts.append(f"参会人: {', '.join(participant_names[:5])}")
        elif participant_names:
            description_parts.append(f"参会人: {len(participant_names)}人")
        
        # 添加压缩的metadata
        description_parts.append(metadata_compact)
        description = "\n".join(description_parts)
        
        # 计算日期时间（使用ISO8601格式字符串）
        start_dt = datetime.fromtimestamp(start_time)
        # 格式：YYYY-MM-DDTHH:MM:SS
        event_date_time = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
        duration = end_time - start_time
        
        logger.debug(f"📅 会议事件时间: {event_date_time}, 持续时间: {duration}秒")
        
        return self.create_one_time_event(
            title=topic,
            duration=duration,
            description=description,
            location=location,
            timezone=timezone,
            event_date_time=event_date_time
        )
    
    @staticmethod
    def parse_meeting_metadata(description: str) -> Optional[Dict]:
        """从事件描述中解析会议metadata"""
        try:
            # 兼容新旧格式
            # 新格式：[M:reserve_id:event_id:calendar_id]
            if "[M:" in description:
                compact_str = description.split("[M:")[1].split("]")[0]
                parts = compact_str.split(":")
                return {
                    "type": "meeting",
                    "reserve_id": parts[0] if len(parts) > 0 else "",
                    "event_id": parts[1] if len(parts) > 1 else "",
                    "calendar_id": parts[2] if len(parts) > 2 else ""
                }
            # 旧格式：[Metadata: {...}]
            elif "[Metadata:" in description:
                metadata_str = description.split("[Metadata:")[1].split("]")[0].strip()
                return json.loads(metadata_str)
        except Exception as e:
            logger.warning(f"解析会议metadata失败: {e}")
        return None
    
    def find_meeting_events(
        self,
        reserve_id: Optional[str] = None,
        event_id: Optional[str] = None,
        range_start: Optional[str] = None,
        range_end: Optional[str] = None
    ) -> List[Dict]:
        """查找会议事件
        
        通过查询所有事件，然后筛选包含指定metadata的事件
        """
        # 查询所有事件
        result_str = self.query_events(
            range_start=range_start,
            range_end=range_end
        )
        
        # 解析结果（这里需要根据实际返回格式解析）
        # MCP工具返回的可能是JSON字符串或文本
        events = []
        try:
            # 尝试解析为JSON
            if isinstance(result_str, str):
                # 尝试解析JSON
                try:
                    parsed = json.loads(result_str)
                    # 如果解析成功，检查格式
                    if isinstance(parsed, list):
                        events = parsed
                    elif isinstance(parsed, dict):
                        # queryAllEventInstances 返回格式: {"eventInstanceList": [...]}
                        # 也可能包含instances或events字段（兼容其他格式）
                        events = parsed.get("eventInstanceList", 
                                           parsed.get("instances", 
                                                     parsed.get("events", [])))
                        logger.debug(f"📋 从返回结果中提取到 {len(events)} 个事件（字段: eventInstanceList/instances/events）")
                    else:
                        logger.warning(f"无法解析事件查询结果格式: {type(parsed)}")
                        return []
                except json.JSONDecodeError:
                    # 如果不是JSON，可能是纯文本，尝试其他解析方式
                    logger.warning(f"事件查询结果不是JSON格式: {result_str[:100]}")
                    # 如果返回的是错误信息，返回空列表
                    if "Failed" in result_str or "Error" in result_str:
                        logger.warning(f"查询事件失败: {result_str}")
                        return []
                    return []
            else:
                events = result_str if isinstance(result_str, list) else []
        except Exception as e:
            logger.error(f"解析事件查询结果失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
        
        logger.debug(f"📊 解析后得到 {len(events)} 个事件，开始筛选会议事件...")
        
        # 如果事件列表为空，记录原始返回结果（用于调试）
        if not events:
            logger.warning(f"⚠️ 查询返回的事件列表为空，原始返回结果: {result_str[:500] if isinstance(result_str, str) else str(result_str)[:500]}")
        
        # 筛选会议事件
        meeting_events = []
        for i, event in enumerate(events):
            # 获取事件的基本信息（用于调试）
            # 注意：使用 calendar_event_id 避免与函数参数 event_id 冲突
            calendar_event_id = event.get("id") or event.get("eventId")
            event_title = event.get("title", "")
            
            # 获取描述（可能是description字段）
            description = event.get("description", "") or event.get("desc", "")
            
            # 记录每个事件的详细信息（用于调试）
            logger.debug(f"📋 检查事件 {i+1}/{len(events)}: id={calendar_event_id}, title={event_title}, description长度={len(description)}")
            if description:
                logger.debug(f"   描述内容: {description[:100]}")
            
            metadata = self.parse_meeting_metadata(description)
            
            # 如果解析到metadata且类型是meeting，则认为是会议事件
            if metadata and metadata.get("type") == "meeting":
                # 如果指定了reserve_id或event_id，进行匹配
                # 注意：这里的 reserve_id 和 event_id 是函数参数，用于匹配metadata中的值
                # 只有当函数参数不为 None 时才进行匹配
                if reserve_id is not None and metadata.get("reserve_id") != reserve_id:
                    logger.debug(f"📋 跳过事件（reserve_id不匹配）: id={calendar_event_id}, 期望={reserve_id}, 实际={metadata.get('reserve_id')}, metadata={metadata}")
                    continue
                # 只有当函数参数 event_id 不为 None 时才进行匹配
                if event_id is not None and metadata.get("event_id") != event_id:
                    logger.debug(f"📋 跳过事件（event_id不匹配）: id={calendar_event_id}, 期望={event_id}, 实际={metadata.get('event_id')}, metadata={metadata}")
                    continue
                
                logger.info(f"✅ 找到会议事件: id={calendar_event_id}, title={event_title}, metadata={metadata}")
                meeting_events.append({
                    **event,
                    "meeting_metadata": metadata
                })
            else:
                # 如果没有metadata，记录一下（用于调试）
                if description:
                    logger.debug(f"📋 非会议事件: id={calendar_event_id}, title={event_title}, description前100字符={description[:100]}")
                    # 检查是否包含会议相关的关键词
                    if "[M:" in description or "会议" in description or "meeting" in description.lower():
                        logger.warning(f"⚠️ 事件可能包含会议信息但metadata解析失败: id={calendar_event_id}, description={description[:200]}")
        
        logger.info(f"📅 筛选后找到 {len(meeting_events)} 个会议事件（共 {len(events)} 个事件）")
        return meeting_events

