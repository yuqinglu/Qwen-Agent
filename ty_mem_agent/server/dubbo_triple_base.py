# -*- coding: utf-8 -*-
"""
Dubbo Triple (JSON / h2c) 公共基类

提供：
- BaseDubboTripleConfig：保存 Nacos 地址、应用名、接口名及直连参数
- BaseDubboTripleClient：Nacos 服务发现 + HTTP/2 Prior Knowledge (h2c) 传输层

各业务客户端继承 BaseDubboTripleClient，只需传入配置并实现业务方法。
"""

import json
import socket
from typing import Any, Dict, Optional, Tuple

from loguru import logger

try:
    import nacos  # type: ignore
except ImportError:
    nacos = None  # type: ignore

try:
    import h2.config  # type: ignore
    import h2.connection  # type: ignore
    import h2.events  # type: ignore
    _h2_available = True
except ImportError:
    _h2_available = False


class BaseDubboTripleConfig:
    """Dubbo Triple 客户端公共配置"""

    def __init__(
        self,
        nacos_addr: str,
        nacos_namespace: str,
        application_name: str,
        interface_name: str,
        direct_host: Optional[str] = None,
        direct_port: Optional[int] = None,
        use_tls: bool = False,
        timeout: int = 30,
    ) -> None:
        self.nacos_addr = nacos_addr
        self.nacos_namespace = nacos_namespace
        self.application_name = application_name
        self.interface_name = interface_name
        self.direct_host = direct_host
        self.direct_port = direct_port
        self.use_tls = use_tls
        self.timeout = timeout


class BaseDubboTripleClient:
    """Nacos 服务发现 + Dubbo Triple JSON (h2c) 传输基类"""

    def __init__(self, config: BaseDubboTripleConfig) -> None:
        if nacos is None:
            logger.warning(
                "nacos-sdk-python 未安装，将无法通过 Nacos 自动发现 "
                f"{config.application_name}。"
            )
        self._config = config
        self._base_url: Optional[str] = None

    def _ensure_base_url(self) -> str:
        if self._base_url is not None:
            return self._base_url
        host, port = self._discover_triple_endpoint()
        scheme = "https" if self._config.use_tls else "http"
        self._base_url = f"{scheme}://{host}:{port}"
        logger.info(f"📡 选用 Triple 端点 [{self._config.application_name}]: {self._base_url}")
        return self._base_url

    def _discover_triple_endpoint(self) -> Tuple[str, int]:
        cfg = self._config

        if cfg.direct_host and cfg.direct_port:
            logger.info(f"📡 直连 Triple 端点: {cfg.direct_host}:{cfg.direct_port}")
            return cfg.direct_host, int(cfg.direct_port)

        if nacos is None:
            raise RuntimeError(
                f"未配置直连地址且 nacos-sdk-python 未安装，"
                f"无法发现 {cfg.application_name} 的 Triple 端点。"
            )

        logger.info(
            f"🔍 通过 Nacos({cfg.nacos_addr}, ns={cfg.nacos_namespace}) "
            f"发现服务 {cfg.application_name}"
        )
        client = nacos.NacosClient(cfg.nacos_addr, namespace=cfg.nacos_namespace)

        if hasattr(client, "select_one_health_instance"):
            instance = client.select_one_health_instance(cfg.application_name)
            if not instance:
                raise RuntimeError(
                    f"在 Nacos 上未找到服务 {cfg.application_name} 的健康实例"
                )
        else:
            instances = client.list_naming_instance(cfg.application_name)
            hosts = instances.get("hosts") if isinstance(instances, dict) else None
            if not hosts:
                raise RuntimeError(
                    f"在 Nacos 上未找到服务 {cfg.application_name} 的实例列表"
                )
            instance = next((h for h in hosts if h.get("healthy", True)), None)
            if not instance:
                raise RuntimeError(
                    f"在 Nacos 上未找到服务 {cfg.application_name} 的健康实例"
                )

        host = instance.get("ip") or instance.get("host")
        port = instance.get("port")
        if not host or not port:
            raise RuntimeError(f"Nacos 实例信息缺少 ip/port: {instance}")
        return host, int(port)

    def _request_triple(
        self,
        method: str,
        body: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        向 `/{interface_name}/{method}` 发送 Dubbo Triple JSON (h2c) 请求。
        """
        from urllib.parse import urlparse

        cfg = self._config
        base_url = self._ensure_base_url()
        parsed = urlparse(base_url)
        host = parsed.hostname
        port = parsed.port or (443 if cfg.use_tls else 80)
        path = f"/{cfg.interface_name}/{method}"

        body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        logger.info(f"🌐 Triple h2c 请求: {base_url}{path}, timeout={cfg.timeout}s")
        logger.debug(f"📤 请求体 JSON: {body}")

        resp_bytes = BaseDubboTripleClient._post_h2c(host, port, path, body_bytes, cfg.timeout)

        try:
            data = json.loads(resp_bytes)
        except Exception as exc:
            raise RuntimeError(f"Triple 返回非 JSON: {resp_bytes!r}") from exc

        if not isinstance(data, dict):
            raise RuntimeError(f"Triple 返回 JSON 但不是对象: {data}")

        logger.debug(f"📩 Triple 响应 JSON: {data}")

        status_field = data.get("status")
        if status_field is not None and str(status_field) not in ("200", "0", ""):
            raw_msg = data.get("message") or data.get("msg") or str(data)
            first_line = str(raw_msg).split("\n")[0].strip()
            raise RuntimeError(
                f"服务端返回业务错误 [status={status_field}]: {first_line}"
            )

        return data

    @staticmethod
    def _post_h2c(
        host: str,
        port: int,
        path: str,
        body_bytes: bytes,
        timeout: int,
    ) -> bytes:
        """
        HTTP/2 Prior Knowledge (h2c) POST 请求。

        Dubbo Triple 服务端只接受 HTTP/2，对 http:// 明文地址使用 h2c Prior Knowledge：
        直接发送 PRI * HTTP/2.0 连接前言，跳过 HTTP/1.1 Upgrade 协商。

        依赖 h2 库（httpx[http2] 的传递依赖，无需额外安装）。
        """
        if not _h2_available:
            raise RuntimeError("缺少 h2 依赖，请执行: pip install httpx[http2]")

        sock = socket.create_connection((host, port), timeout=timeout)
        sock.settimeout(timeout)
        try:
            config = h2.config.H2Configuration(
                client_side=True, header_encoding="utf-8"
            )
            conn = h2.connection.H2Connection(config=config)
            conn.initiate_connection()
            sock.sendall(conn.data_to_send())

            req_headers = [
                (":method", "POST"),
                (":path", path),
                (":authority", f"{host}:{port}"),
                (":scheme", "http"),
                ("content-type", "application/json"),
                ("content-length", str(len(body_bytes))),
            ]
            conn.send_headers(stream_id=1, headers=req_headers)
            conn.send_data(stream_id=1, data=body_bytes, end_stream=True)
            sock.sendall(conn.data_to_send())

            response_body = b""
            stream_ended = False

            while not stream_ended:
                try:
                    data = sock.recv(65535)
                except OSError:
                    break
                if not data:
                    break

                events = conn.receive_data(data)
                pending = conn.data_to_send()
                if pending:
                    sock.sendall(pending)

                for event in events:
                    if isinstance(event, h2.events.DataReceived):
                        response_body += event.data
                        conn.acknowledge_received_data(
                            event.flow_controlled_length, event.stream_id
                        )
                        pending = conn.data_to_send()
                        if pending:
                            sock.sendall(pending)
                    elif isinstance(event, h2.events.StreamEnded):
                        stream_ended = True
        finally:
            sock.close()

        return response_body
