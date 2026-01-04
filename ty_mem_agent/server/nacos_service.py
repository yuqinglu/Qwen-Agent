#!/usr/bin/env python3
"""
Nacos服务注册模块
目前使用Reqeusts进行注册，如果后面需要服务发现、配置管理等，再考虑迁移到SDK更合适
用于将APP API接口注册到Nacos服务注册中心
"""

import json
import asyncio
import threading
from typing import List, Dict, Optional, Any
from urllib.parse import quote
from loguru import logger

try:
    import requests
except ImportError:
    requests = None
    logger.warning("requests 未安装，Nacos服务注册功能将不可用。请运行: pip install requests")


class NacosServiceRegistry:
    """Nacos服务注册管理器"""
    
    def __init__(self, 
                 server_addresses: str,
                 namespace: Optional[str] = None,
                 username: Optional[str] = None,
                 password: Optional[str] = None,
                 service_name: str = "ty-memory-agent",
                 group_name: Optional[str] = None):
        """
        初始化Nacos服务注册管理器
        
        Args:
            server_addresses: Nacos服务器地址，格式：ip:port 或 ip1:port1,ip2:port2
            namespace: 命名空间（可选）
            username: 用户名（可选）
            password: 密码（可选）
            service_name: 服务名称
            group_name: 服务组名
        """
        if requests is None:
            raise ImportError("requests 未安装，请运行: pip install requests")
        
        self.server_addresses = server_addresses
        self.namespace = namespace or "public"
        self.username = username
        self.password = password
        self.service_name = service_name
        # group_name 不是必须的，如果不设置，Nacos会使用默认值 DEFAULT_GROUP
        # 这里保存原始值，如果为None则在实际调用时不传递该参数
        self.group_name = group_name
        
        # 解析服务器地址（取第一个地址作为主地址）
        primary_addr = server_addresses.split(',')[0].strip()
        if ':' in primary_addr:
            self.server_host, self.server_port = primary_addr.rsplit(':', 1)
            self.server_port = int(self.server_port.strip())
        else:
            self.server_host = primary_addr.strip()
            self.server_port = 8848  # 默认端口
        
        self.base_url = f"http://{self.server_host}:{self.server_port}"
        self.registered_instances: List[Dict] = []
        
        # 心跳相关
        self.heartbeat_interval = 5  # Nacos 默认心跳间隔 5 秒
        self.heartbeat_thread: Optional[threading.Thread] = None
        self.heartbeat_stop_event = threading.Event()
        self.heartbeat_running = False
        
        logger.info(f"✅ Nacos客户端初始化成功: {self.base_url}")
        if namespace and namespace != "public":
            logger.info(f"   命名空间: {namespace}")
    
    def register_api_services(self, 
                             host: str, 
                             port: int, 
                             api_routes: List[Dict[str, Any]],
                             metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        注册所有API接口到Nacos
        
        Args:
            host: 服务主机地址
            port: 服务端口
            api_routes: API路由列表，每个路由包含：
                - path: 接口路径
                - method: HTTP方法（GET/POST/PUT/DELETE/WS等）
                - description: 接口描述
            metadata: 额外的元数据（可选）
        
        Returns:
            是否注册成功
        """
        if requests is None:
            logger.error("❌ requests 未安装，无法注册服务")
            return False
        
        try:
            # 构建服务元数据（简化版本，避免metadata过大）
            service_metadata = {
                'api_count': str(len(api_routes)),
                'modules': ','.join(list(set(route.get('module', '') for route in api_routes)))
            }
            if metadata:
                # 将 metadata 中的值转换为字符串
                for key, value in metadata.items():
                    if isinstance(value, (list, dict)):
                        # 列表和字典转换为逗号分隔的字符串
                        service_metadata[key] = ','.join(str(v) for v in value) if isinstance(value, list) else json.dumps(value, ensure_ascii=False)
                    else:
                        service_metadata[key] = str(value)
            
            # Nacos metadata 格式要求：key1=value1,key2=value2
            # 注意：值中不能包含逗号和等号，需要 URL 编码
            metadata_pairs = []
            for key, value in service_metadata.items():
                # 对值进行 URL 编码，避免特殊字符问题
                # 使用 safe='' 表示不保留任何字符，全部编码
                encoded_value = quote(str(value), safe='')
                metadata_pairs.append(f"{key}={encoded_value}")
            
            metadata_str = ','.join(metadata_pairs)
            
            # 使用Nacos OpenAPI注册服务实例
            url = f"{self.base_url}/nacos/v1/ns/instance"
            params = {
                'serviceName': self.service_name,
                'ip': host,
                'port': port,
                'ephemeral': 'true',  # 临时实例
                'healthy': 'true',
                'enabled': 'true',
                'metadata': metadata_str
            }
            
            # groupName 不是必须参数，如果不设置或为默认值，可以不传递
            # 但为了明确性，如果明确设置了非默认值，则传递
            if self.group_name and self.group_name != "DEFAULT_GROUP":
                params['groupName'] = self.group_name
            
            if self.namespace and self.namespace != "public":
                params['namespaceId'] = self.namespace
            
            # 如果有认证信息，添加到请求中
            auth = None
            if self.username and self.password:
                auth = (self.username, self.password)
            
            response = requests.post(url, params=params, auth=auth, timeout=5)
            
            if response.status_code == 200 and response.text == "ok":
                logger.info(f"✅ 服务注册成功: {self.service_name} @ {host}:{port}")
                logger.info(f"   已注册 {len(api_routes)} 个API接口")
                
                # 保存注册信息
                instance_info = {
                    'service_name': self.service_name,
                    'group_name': self.group_name,
                    'ip': host,
                    'port': port,
                    'metadata': service_metadata,
                    'api_routes': api_routes  # 完整路由信息保存在内存中
                }
                self.registered_instances.append(instance_info)
                
                # 启动心跳任务（ephemeral 实例需要定期发送心跳）
                if not self.heartbeat_running:
                    self._start_heartbeat()
                
                return True
            else:
                logger.error(f"❌ 服务注册失败: {self.service_name} @ {host}:{port}")
                logger.error(f"   响应状态: {response.status_code}, 响应内容: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ 注册服务到Nacos时出错: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False
    
    def deregister_service(self, host: str, port: int) -> bool:
        """
        注销服务实例
        
        Args:
            host: 服务主机地址
            port: 服务端口
        
        Returns:
            是否注销成功
        """
        if requests is None:
            return False
        
        try:
            # 使用Nacos OpenAPI注销服务实例
            url = f"{self.base_url}/nacos/v1/ns/instance"
            params = {
                'serviceName': self.service_name,
                'ip': host,
                'port': port,
                'ephemeral': 'true'
            }
            
            # groupName 不是必须参数，如果不设置或为默认值，可以不传递
            if self.group_name and self.group_name != "DEFAULT_GROUP":
                params['groupName'] = self.group_name
            
            if self.namespace and self.namespace != "public":
                params['namespaceId'] = self.namespace
            
            # 如果有认证信息，添加到请求中
            auth = None
            if self.username and self.password:
                auth = (self.username, self.password)
            
            response = requests.delete(url, params=params, auth=auth, timeout=5)
            
            if response.status_code == 200 and response.text == "ok":
                logger.info(f"✅ 服务注销成功: {self.service_name} @ {host}:{port}")
                # 从已注册列表中移除
                self.registered_instances = [
                    inst for inst in self.registered_instances
                    if not (inst['ip'] == host and inst['port'] == port)
                ]
                
                # 如果没有已注册的实例了，停止心跳
                if not self.registered_instances:
                    self._stop_heartbeat()
                
                return True
            else:
                logger.warning(f"⚠️ 服务注销失败: {self.service_name} @ {host}:{port}")
                logger.warning(f"   响应状态: {response.status_code}, 响应内容: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ 注销服务时出错: {e}")
            return False
    
    def deregister_all(self) -> bool:
        """注销所有已注册的服务实例"""
        # 停止心跳
        self._stop_heartbeat()
        
        success = True
        for inst in self.registered_instances.copy():
            if not self.deregister_service(inst['ip'], inst['port']):
                success = False
        return success
    
    def _start_heartbeat(self):
        """启动心跳任务"""
        if self.heartbeat_running:
            return
        
        self.heartbeat_stop_event.clear()
        self.heartbeat_running = True
        
        def heartbeat_worker():
            """心跳工作线程"""
            while not self.heartbeat_stop_event.is_set():
                try:
                    # 为所有已注册的实例发送心跳
                    for inst in self.registered_instances.copy():
                        self._send_heartbeat(inst['ip'], inst['port'])
                    
                    # 等待心跳间隔时间
                    if self.heartbeat_stop_event.wait(self.heartbeat_interval):
                        break  # 收到停止信号
                except Exception as e:
                    logger.error(f"❌ 发送心跳时出错: {e}")
                    # 出错后继续，等待下次心跳
            
            self.heartbeat_running = False
            logger.info("🛑 Nacos心跳任务已停止")
        
        self.heartbeat_thread = threading.Thread(target=heartbeat_worker, daemon=True, name="NacosHeartbeat")
        self.heartbeat_thread.start()
        logger.info(f"✅ Nacos心跳任务已启动（间隔: {self.heartbeat_interval}秒）")
    
    def _stop_heartbeat(self):
        """停止心跳任务"""
        if not self.heartbeat_running:
            return
        
        self.heartbeat_stop_event.set()
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            self.heartbeat_thread.join(timeout=2)
        self.heartbeat_running = False
    
    def _send_heartbeat(self, host: str, port: int) -> bool:
        """
        发送心跳到Nacos
        
        Args:
            host: 服务主机地址
            port: 服务端口
        
        Returns:
            是否发送成功
        """
        if requests is None:
            return False
        
        try:
            # Nacos 心跳接口
            url = f"{self.base_url}/nacos/v1/ns/instance/beat"
            params = {
                'serviceName': self.service_name,
                'ip': host,
                'port': port,
                'ephemeral': 'true'
            }
            
            if self.group_name and self.group_name != "DEFAULT_GROUP":
                params['groupName'] = self.group_name
            
            if self.namespace and self.namespace != "public":
                params['namespaceId'] = self.namespace
            
            # 如果有认证信息，添加到请求中
            auth = None
            if self.username and self.password:
                auth = (self.username, self.password)
            
            response = requests.put(url, params=params, auth=auth, timeout=3)
            
            if response.status_code == 200:
                # 心跳成功（Nacos 返回 JSON，包含客户端心跳间隔建议）
                try:
                    result = response.json()
                    if 'clientBeatInterval' in result:
                        # 使用 Nacos 建议的心跳间隔
                        suggested_interval = result.get('clientBeatInterval', self.heartbeat_interval) / 1000  # 转换为秒
                        if suggested_interval != self.heartbeat_interval:
                            self.heartbeat_interval = int(suggested_interval)
                            logger.debug(f"📡 Nacos建议心跳间隔: {self.heartbeat_interval}秒")
                except:
                    pass  # 忽略JSON解析错误
                return True
            else:
                logger.warning(f"⚠️ 心跳发送失败: {host}:{port}, 状态: {response.status_code}")
                return False
                
        except Exception as e:
            logger.warning(f"⚠️ 发送心跳时出错: {e}")
            return False
    
    def get_registered_instances(self) -> List[Dict]:
        """获取所有已注册的服务实例信息"""
        return self.registered_instances.copy()


def extract_api_routes_from_design() -> List[Dict[str, Any]]:
    """
    从APP_API_DESIGN.md文档中提取API接口定义
    这些接口将注册到Nacos
    
    Returns:
        API路由列表
    """
    # 根据APP_API_DESIGN.md文档定义的接口列表
    # 文档位置：ty_mem_agent/doc/APP_API_DESIGN.md 第7.1节
    api_routes = [
        # ASR语音识别接口
        {
            'path': '/api/v1/asr/recognize',
            'method': 'POST',
            'description': '语音识别（支持流式/非流式输出，通过 stream_output 参数控制）',
            'module': 'ASR'
        },
        {
            'path': '/api/v1/asr/stream',
            'method': 'WS',
            'description': '实时流式语音识别（边说边识别，音频流输入）',
            'module': 'ASR'
        },
        
        # 待办创建接口
        {
            'path': '/api/v1/todo/quick-create',
            'method': 'POST',
            'description': '一句话创建待办（文本）',
            'module': '待办创建'
        },
        {
            'path': '/api/v1/todo/quick-create-voice',
            'method': 'POST',
            'description': '一句话创建待办（语音）',
            'module': '待办创建'
        },
        {
            'path': '/api/v1/todo/extract-params',
            'method': 'POST',
            'description': '提取待办核心参数（不创建待办）',
            'module': '待办创建'
        },
        
        # 待办聊天接口
        {
            'path': '/api/v1/todo/{event_id}/chat/sessions',
            'method': 'POST',
            'description': '创建聊天会话（可带初始消息和待办内容）',
            'module': '待办聊天'
        },
        {
            'path': '/api/v1/todo/{event_id}/chat/sessions',
            'method': 'GET',
            'description': '获取会话列表',
            'module': '待办聊天'
        },
        {
            'path': '/api/v1/todo/{event_id}/chat/sessions/{session_id}',
            'method': 'GET',
            'description': '获取会话详情（含历史消息）',
            'module': '待办聊天'
        },
        {
            'path': '/api/v1/todo/{event_id}/chat/sessions/{session_id}/delete',
            'method': 'POST',
            'description': '删除会话',
            'module': '待办聊天'
        },
        {
            'path': '/api/v1/todo/{event_id}/chat/sessions/{session_id}/update-title',
            'method': 'POST',
            'description': '更新会话标题',
            'module': '待办聊天'
        },
        {
            'path': '/api/v1/todo/{event_id}/chat/sessions/{session_id}/messages',
            'method': 'GET',
            'description': '获取消息列表（分页）',
            'module': '待办聊天'
        },
        {
            'path': '/api/v1/todo/{event_id}/chat/sessions/{session_id}/messages',
            'method': 'POST',
            'description': '发送消息（服务端自动获取历史，客户端只发当前消息）',
            'module': '待办聊天'
        },
        {
            'path': '/api/v1/todo/{event_id}/chat/sessions/stream',
            'method': 'POST',
            'description': '创建/发送消息（SSE流式返回）【推荐】',
            'module': '待办聊天'
        },
        {
            'path': '/api/v1/todo/chat/confirm-suggested-todo',
            'method': 'POST',
            'description': '确认建议待办，转为正式待办',
            'module': '待办聊天'
        },
        {
            'path': '/api/v1/todo/{event_id}/chat/ws',
            'method': 'WS',
            'description': '流式聊天',
            'module': '待办聊天'
        },
        
        # 富媒体卡片接口
        {
            'path': '/api/v1/todo/{event_id}/cards',
            'method': 'GET',
            'description': '获取待办的所有富媒体卡片',
            'module': '富媒体卡片'
        },
        {
            'path': '/api/v1/todo/{event_id}/cards',
            'method': 'POST',
            'description': '创建富媒体卡片',
            'module': '富媒体卡片'
        },
        {
            'path': '/api/v1/todo/cards/{card_id}',
            'method': 'GET',
            'description': '获取单个富媒体卡片',
            'module': '富媒体卡片'
        },
        {
            'path': '/api/v1/todo/cards/{card_id}/update',
            'method': 'POST',
            'description': '更新富媒体卡片',
            'module': '富媒体卡片'
        },
        {
            'path': '/api/v1/todo/cards/{card_id}/delete',
            'method': 'POST',
            'description': '删除富媒体卡片',
            'module': '富媒体卡片'
        },
        {
            'path': '/api/v1/todo/cards/types',
            'method': 'GET',
            'description': '获取支持的卡片类型列表',
            'module': '富媒体卡片'
        },
    ]
    
    return api_routes


# 全局Nacos注册管理器实例
_nacos_registry: Optional[NacosServiceRegistry] = None


def get_nacos_registry() -> Optional[NacosServiceRegistry]:
    """获取Nacos注册管理器实例（单例）"""
    global _nacos_registry
    return _nacos_registry


def init_nacos_registry(settings) -> Optional[NacosServiceRegistry]:
    """
    初始化Nacos注册管理器
    
    Args:
        settings: 配置对象
    
    Returns:
        Nacos注册管理器实例，如果未启用则返回None
    """
    global _nacos_registry
    
    if not getattr(settings, 'NACOS_ENABLED', False):
        logger.info("ℹ️ Nacos服务注册未启用")
        return None
    
    if requests is None:
        logger.warning("⚠️ requests 未安装，Nacos服务注册功能将不可用")
        logger.warning("   请运行: pip install requests")
        return None
    
    try:
        _nacos_registry = NacosServiceRegistry(
            server_addresses=getattr(settings, 'NACOS_SERVER_ADDRESSES', 'localhost:8848'),
            namespace=getattr(settings, 'NACOS_NAMESPACE', None),
            username=getattr(settings, 'NACOS_USERNAME', None),
            password=getattr(settings, 'NACOS_PASSWORD', None),
            service_name=getattr(settings, 'NACOS_SERVICE_NAME', 'ty-memory-agent'),
            group_name=getattr(settings, 'NACOS_GROUP_NAME', None)  # 可选，不设置时使用Nacos默认值
        )
        logger.info("✅ Nacos注册管理器初始化成功")
        return _nacos_registry
    except Exception as e:
        logger.error(f"❌ 初始化Nacos注册管理器失败: {e}")
        return None

