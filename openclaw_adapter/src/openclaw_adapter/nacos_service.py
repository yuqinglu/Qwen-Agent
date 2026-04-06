# -*- coding: utf-8 -*-
"""
Nacos 服务注册（OpenAPI + requests），与 ty_mem_agent.server.nacos_service 行为对齐。
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, List, Optional
from urllib.parse import quote

try:
    import requests
except ImportError:
    requests = None  # type: ignore

from openclaw_adapter.constants import API_URL_PREFIX

logger = logging.getLogger(__name__)


class NacosServiceRegistry:
    """Nacos 服务注册管理器"""

    def __init__(
        self,
        server_addresses: str,
        namespace: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        service_name: str = "openclaw-adapter",
        group_name: Optional[str] = None,
    ):
        if requests is None:
            raise ImportError("requests 未安装，请安装: pip install requests")

        self.server_addresses = server_addresses
        self.namespace = namespace or "public"
        self.username = username
        self.password = password
        self.service_name = service_name
        self.group_name = group_name

        primary_addr = server_addresses.split(",")[0].strip()
        if ":" in primary_addr:
            self.server_host, port_str = primary_addr.rsplit(":", 1)
            self.server_port = int(port_str.strip())
        else:
            self.server_host = primary_addr.strip()
            self.server_port = 8848

        self.base_url = f"http://{self.server_host}:{self.server_port}"
        self.registered_instances: List[Dict[str, Any]] = []

        self.heartbeat_interval = 5
        self.heartbeat_thread: Optional[threading.Thread] = None
        self.heartbeat_stop_event = threading.Event()
        self.heartbeat_running = False

        logger.info("Nacos client ready: %s", self.base_url)
        if namespace and namespace != "public":
            logger.info("Nacos namespace: %s", namespace)

    def register_api_services(
        self,
        host: str,
        port: int,
        api_routes: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if requests is None:
            logger.error("requests not installed, cannot register with Nacos")
            return False

        try:
            service_metadata: Dict[str, str] = {
                "api_count": str(len(api_routes)),
                "modules": ",".join(
                    sorted({route.get("module", "") for route in api_routes if route.get("module")})
                ),
            }
            if metadata:
                for key, value in metadata.items():
                    if isinstance(value, (list, dict)):
                        service_metadata[key] = (
                            ",".join(str(v) for v in value)
                            if isinstance(value, list)
                            else json.dumps(value, ensure_ascii=False)
                        )
                    else:
                        service_metadata[key] = str(value)

            metadata_pairs = []
            for key, value in service_metadata.items():
                encoded_value = quote(str(value), safe="")
                metadata_pairs.append(f"{key}={encoded_value}")
            metadata_str = ",".join(metadata_pairs)

            url = f"{self.base_url}/nacos/v1/ns/instance"
            params: Dict[str, Any] = {
                "serviceName": self.service_name,
                "ip": host,
                "port": port,
                "ephemeral": "true",
                "healthy": "true",
                "enabled": "true",
                "metadata": metadata_str,
            }
            if self.group_name and self.group_name != "DEFAULT_GROUP":
                params["groupName"] = self.group_name
            if self.namespace and self.namespace != "public":
                params["namespaceId"] = self.namespace

            auth = None
            if self.username and self.password:
                auth = (self.username, self.password)

            response = requests.post(url, params=params, auth=auth, timeout=5)

            if response.status_code == 200 and response.text == "ok":
                logger.info(
                    "Nacos register ok: %s @ %s:%s (%s routes)",
                    self.service_name,
                    host,
                    port,
                    len(api_routes),
                )
                self.registered_instances.append(
                    {
                        "service_name": self.service_name,
                        "group_name": self.group_name,
                        "ip": host,
                        "port": port,
                        "metadata": service_metadata,
                        "api_routes": api_routes,
                    }
                )
                if not self.heartbeat_running:
                    self._start_heartbeat()
                return True

            logger.error(
                "Nacos register failed: %s @ %s:%s status=%s body=%s",
                self.service_name,
                host,
                port,
                response.status_code,
                response.text[:500],
            )
            return False
        except Exception as e:
            logger.exception("Nacos register error: %s", e)
            return False

    def deregister_service(self, host: str, port: int) -> bool:
        if requests is None:
            return False
        try:
            url = f"{self.base_url}/nacos/v1/ns/instance"
            params: Dict[str, Any] = {
                "serviceName": self.service_name,
                "ip": host,
                "port": port,
                "ephemeral": "true",
            }
            if self.group_name and self.group_name != "DEFAULT_GROUP":
                params["groupName"] = self.group_name
            if self.namespace and self.namespace != "public":
                params["namespaceId"] = self.namespace
            auth = None
            if self.username and self.password:
                auth = (self.username, self.password)
            response = requests.delete(url, params=params, auth=auth, timeout=5)
            if response.status_code == 200 and response.text == "ok":
                logger.info("Nacos deregister ok: %s @ %s:%s", self.service_name, host, port)
                self.registered_instances = [
                    inst
                    for inst in self.registered_instances
                    if not (inst["ip"] == host and inst["port"] == port)
                ]
                if not self.registered_instances:
                    self._stop_heartbeat()
                return True
            logger.warning(
                "Nacos deregister failed: %s @ %s:%s status=%s",
                self.service_name,
                host,
                port,
                response.status_code,
            )
            return False
        except Exception as e:
            logger.error("Nacos deregister error: %s", e)
            return False

    def _start_heartbeat(self) -> None:
        if self.heartbeat_running:
            return
        self.heartbeat_stop_event.clear()
        self.heartbeat_running = True

        def heartbeat_worker() -> None:
            while not self.heartbeat_stop_event.is_set():
                try:
                    for inst in self.registered_instances.copy():
                        self._send_heartbeat(inst["ip"], inst["port"])
                    if self.heartbeat_stop_event.wait(self.heartbeat_interval):
                        break
                except Exception as e:
                    logger.error("Nacos heartbeat error: %s", e)
            self.heartbeat_running = False
            logger.info("Nacos heartbeat stopped")

        self.heartbeat_thread = threading.Thread(
            target=heartbeat_worker, daemon=True, name="NacosHeartbeat"
        )
        self.heartbeat_thread.start()
        logger.info("Nacos heartbeat started (interval=%ss)", self.heartbeat_interval)

    def _stop_heartbeat(self) -> None:
        if not self.heartbeat_running:
            return
        self.heartbeat_stop_event.set()
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            self.heartbeat_thread.join(timeout=2)
        self.heartbeat_running = False

    def _send_heartbeat(self, host: str, port: int) -> bool:
        if requests is None:
            return False
        try:
            url = f"{self.base_url}/nacos/v1/ns/instance/beat"
            params: Dict[str, Any] = {
                "serviceName": self.service_name,
                "ip": host,
                "port": port,
                "ephemeral": "true",
            }
            if self.group_name and self.group_name != "DEFAULT_GROUP":
                params["groupName"] = self.group_name
            if self.namespace and self.namespace != "public":
                params["namespaceId"] = self.namespace
            auth = None
            if self.username and self.password:
                auth = (self.username, self.password)
            response = requests.put(url, params=params, auth=auth, timeout=3)
            if response.status_code == 200:
                try:
                    result = response.json()
                    if "clientBeatInterval" in result:
                        suggested = result.get("clientBeatInterval", self.heartbeat_interval * 1000) / 1000
                        if int(suggested) != self.heartbeat_interval:
                            self.heartbeat_interval = int(suggested)
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
                return True
            logger.warning("Nacos heartbeat failed: %s:%s status=%s", host, port, response.status_code)
            return False
        except Exception as e:
            logger.warning("Nacos heartbeat error: %s:%s %s", host, port, e)
            return False


def extract_openclaw_adapter_api_routes() -> List[Dict[str, Any]]:
    """对外 API 列表，写入注册元数据并在控制台可核对（与 main 路由一致）。"""
    p = API_URL_PREFIX
    return [
        {
            "path": f"{p}/health",
            "method": "GET",
            "description": "健康检查",
            "module": "health",
        },
        {
            "path": f"{p}/internal/openclaw/webhook",
            "method": "POST",
            "description": "OpenClaw Gateway 入站 webhook（delivery.mode=webhook）",
            "module": "inbound",
        },
        {
            "path": f"{p}/v1/tasks",
            "method": "POST",
            "description": "创建异步任务（转发 Gateway Cron）",
            "module": "tasks",
        },
        {
            "path": f"{p}/v1/tasks/{{openclaw_task_id}}",
            "method": "GET",
            "description": "查询任务状态",
            "module": "tasks",
        },
        {
            "path": f"{p}/v1/tasks/{{openclaw_task_id}}",
            "method": "DELETE",
            "description": "取消任务",
            "module": "tasks",
        },
        {
            "path": f"{p}/internal/dev/simulate-callback",
            "method": "POST",
            "description": "开发联调：模拟回调（需 ADAPTER_DEV_ENDPOINTS=true）",
            "module": "dev",
        },
    ]


_nacos_registry: Optional[NacosServiceRegistry] = None


def get_nacos_registry() -> Optional[NacosServiceRegistry]:
    return _nacos_registry


def init_nacos_registry(
    *,
    enabled: bool,
    server_addresses: str = "localhost:8848",
    namespace: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    service_name: str = "openclaw-adapter",
    group_name: Optional[str] = None,
) -> Optional[NacosServiceRegistry]:
    global _nacos_registry
    if not enabled:
        logger.info("Nacos registration disabled")
        return None
    if requests is None:
        logger.warning("requests not installed; Nacos registration skipped")
        return None
    try:
        _nacos_registry = NacosServiceRegistry(
            server_addresses=server_addresses,
            namespace=namespace,
            username=username,
            password=password,
            service_name=service_name,
            group_name=group_name,
        )
        logger.info("Nacos registry initialized")
        return _nacos_registry
    except Exception as e:
        logger.error("Nacos registry init failed: %s", e)
        return None
