# -*- coding: utf-8 -*-
"""
UGC 文件服务客户端（Nacos + Dubbo Triple(JSON)）

目标：
- 通过 Nacos 发现 FileApplication（Java 侧 Dubbo 应用，协议为 tri）
- 使用 httpx(HTTP/2) 直接以 JSON 形式调用 UGCService.* 接口（免 IDL）

说明：
- Java 端需开启 Dubbo 3 Triple 协议，接口路径形如：
  /com.tyqy.file.api.dubbo.UGCService/upload
- 本模块只负责“发现一个实例 + 组装 HTTP/2 + JSON 请求”，
  具体字段结构与 Java DTO 一致，由你在联调时调整。
"""

import json
import socket
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from loguru import logger

try:
    import nacos  # type: ignore
except ImportError:  # pragma: no cover - 运行环境未安装时给出友好提示
    nacos = None  # type: ignore

from ty_mem_agent.config.settings import settings


class UGCClientConfig:
    """
    UGC 客户端配置

    这里把所有与 Nacos/Triple 相关的字符串集中管理，方便在一个地方调整。
    """

    # Nacos 注册中心地址/命名空间（从 .env 通过 settings 透传）
    # settings.NACOS_SERVER_ADDRESSES 形如 "host1:8848,host2:8848"，此处先使用第一个地址。
    _nacos_addrs = (settings.NACOS_SERVER_ADDRESSES or "localhost:8848").split(",")
    NACOS_ADDR: str = _nacos_addrs[0].strip()
    NACOS_NAMESPACE: str = settings.NACOS_NAMESPACE or "public"

    # Dubbo 应用名（你提供的服务名）
    APPLICATION_NAME: str = "FileApplication"

    # Dubbo 接口名（Java 侧 UGCService 的全限定类名）
    # 你提供的接口签名为：/com.tyqy.file.api.dubbo.UGCService/upload
    # 这里直接内置该接口名，避免再额外配置。
    UGC_INTERFACE: str = "com.tyqy.file.api.dubbo.UGCService"

    # Triple 协议 HTTP(S) 端口（如无法从 Nacos 元数据解析，可先直连）
    # 示例： settings.UGC_TRIPLE_HOST, settings.UGC_TRIPLE_PORT
    DIRECT_HOST: Optional[str] = getattr(settings, "UGC_TRIPLE_HOST", None)
    DIRECT_PORT: Optional[int] = getattr(settings, "UGC_TRIPLE_PORT", None)
    USE_TLS: bool = bool(getattr(settings, "UGC_TRIPLE_USE_TLS", False))

    # HTTP 超时时间
    REQUEST_TIMEOUT_SECONDS: int = int(
        getattr(settings, "UGC_TRIPLE_TIMEOUT_SECONDS", 30)
    )


class UGCClient:
    """基于 Nacos + Dubbo Triple(JSON) 的 UGC 文件服务客户端封装"""

    def __init__(self) -> None:
        if nacos is None:
            logger.warning("nacos-sdk-python 未安装，将无法通过 Nacos 自动发现 FileApplication。")

        self._base_url: Optional[str] = None

    # ----------------------
    # 底层 HTTP/2 Triple 调用
    # ----------------------
    def _ensure_base_url(self) -> str:
        """
        获取 Triple 服务的 base_url（含协议与 host:port），只解析一次后缓存。
        """
        if self._base_url is not None:
            return self._base_url

        host, port = self._discover_triple_endpoint()
        scheme = "https" if UGCClientConfig.USE_TLS else "http"
        self._base_url = f"{scheme}://{host}:{port}"
        logger.info(f"📡 选用 Triple 端点: {self._base_url}")
        return self._base_url

    def _discover_triple_endpoint(self) -> Tuple[str, int]:
        """
        发现 Triple 端点：
        1. 如配置了直连 UGC_TRIPLE_HOST/PORT，优先使用
        2. 否则通过 Nacos 获取 FileApplication 的一个健康实例
        """
        # 1) 直连
        if UGCClientConfig.DIRECT_HOST and UGCClientConfig.DIRECT_PORT:
            logger.info(
                "📡 使用直连 Triple 端点: "
                f"{UGCClientConfig.DIRECT_HOST}:{UGCClientConfig.DIRECT_PORT}"
            )
            return UGCClientConfig.DIRECT_HOST, int(UGCClientConfig.DIRECT_PORT)

        # 2) Nacos 发现
        if nacos is None:
            raise RuntimeError(
                "未配置 UGC_TRIPLE_HOST/PORT 且 nacos-sdk-python 未安装，"
                "无法发现 FileApplication Triple 端点。"
            )

        server_addr = UGCClientConfig.NACOS_ADDR
        namespace = UGCClientConfig.NACOS_NAMESPACE
        logger.info(
            f"🔍 通过 Nacos({server_addr}, ns={namespace}) "
            f"发现服务 {UGCClientConfig.APPLICATION_NAME}"
        )

        client = nacos.NacosClient(server_addr, namespace=namespace)

        # 优先使用较新版本 SDK 提供的 select_one_health_instance
        if hasattr(client, "select_one_health_instance"):
            instance = client.select_one_health_instance(
                UGCClientConfig.APPLICATION_NAME
            )
            if not instance:
                raise RuntimeError(
                    f"在 Nacos 上未找到服务 "
                    f"{UGCClientConfig.APPLICATION_NAME} 的健康实例"
                )
        else:
            # 向后兼容：老版本 SDK 使用 list_naming_instance 再手动挑选健康实例
            instances = client.list_naming_instance(UGCClientConfig.APPLICATION_NAME)
            hosts = instances.get("hosts") if isinstance(instances, dict) else None
            if not hosts:
                raise RuntimeError(
                    f"在 Nacos 上未找到服务 "
                    f"{UGCClientConfig.APPLICATION_NAME} 的实例列表"
                )
            instance = None
            for h in hosts:
                if h.get("healthy", True):
                    instance = h
                    break
            if not instance:
                raise RuntimeError(
                    f"在 Nacos 上未找到服务 "
                    f"{UGCClientConfig.APPLICATION_NAME} 的健康实例（hosts 列表中均不健康）"
                )

        # 通用字段：ip / host + port
        host = instance.get("ip") or instance.get("host")
        port = instance.get("port")
        if not host or not port:
            raise RuntimeError(f"Nacos 实例信息缺少 ip/port: {instance}")

        # 如 Java 侧把 Triple 端口放在 metadata 中，也可以在此做更精细的解析
        # metadata = instance.get("metadata") or {}
        # triple_port = metadata.get("tri_port") ...

        return host, int(port)

    def _request_triple(
        self,
        method: str,
        body: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Dubbo Triple JSON 模式（h2c Prior Knowledge）：
        - Dubbo Triple 基于 gRPC/HTTP2，服务端只接受 HTTP/2 连接
        - 对于 http:// 明文地址，必须使用 h2c Prior Knowledge 握手（直接发送 HTTP/2 连接前言）
        - httpx/httpcore 不原生支持 h2c，因此使用 h2 库 + 原始 TCP socket 实现
        """
        base_url = self._ensure_base_url()
        parsed = urlparse(base_url)
        host = parsed.hostname
        port = parsed.port or (443 if UGCClientConfig.USE_TLS else 80)
        path = f"/{UGCClientConfig.UGC_INTERFACE}/{method}"

        timeout = UGCClientConfig.REQUEST_TIMEOUT_SECONDS
        body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")

        logger.info(f"🌐 Triple h2c 请求: {base_url}{path}, timeout={timeout}s")
        logger.debug(f"📤 请求体 JSON: {body}")

        resp_bytes = UGCClient._post_h2c(host, port, path, body_bytes, timeout)

        try:
            data = json.loads(resp_bytes)
        except Exception as exc:
            raise RuntimeError(f"Triple 返回非 JSON: {resp_bytes!r}") from exc

        if not isinstance(data, dict):
            raise RuntimeError(f"Triple 返回 JSON 但不是对象: {data}")

        logger.debug(f"📩 Triple 响应 JSON: {data}")

        # Dubbo Triple 把服务端异常以 HTTP 200 + {"status":"500","message":"..."} 返回
        # 必须在这里主动检测，否则上层拿到空数据无法知晓真实原因
        status_field = data.get("status")
        if status_field is not None and str(status_field) not in ("200", "0", ""):
            raw_msg = data.get("message") or data.get("msg") or str(data)
            # 只取第一行，避免把整个 Java stack trace 堆进异常消息
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
        try:
            import h2.config  # type: ignore
            import h2.connection  # type: ignore
            import h2.events  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "缺少 h2 依赖，请执行: pip install httpx[http2]"
            ) from exc

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

    # ----------------------
    # 业务方法封装
    # ----------------------
    def upload(
        self,
        bucket: str,
        resource: str,
        user_id: int,
        max_age: int,
        file_list: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        调用 UGCService.upload，返回与 UploadFileResponse 等价的字典结构。

        Args:
            bucket: 存储桶，如 "chat"
            resource: 资源类型，如 "document"、"image"
            user_id: 用户 ID
            max_age: 预签名 URL 有效期（秒）
            file_list: 文件元数据列表，每项包含 fileName/contentType/contentLength/contentMd5
        """
        upload_request = {
            "bucket": bucket,
            "resource": resource,
            "userId": user_id,
            "maxAge": max_age,
            "fileList": [
                {
                    "fileName": f.get("file_name") or f.get("fileName"),
                    "contentType": f.get("content_type") or f.get("contentType"),
                    "contentLength": f.get("content_length") or f.get("contentLength"),
                    "contentMd5": f.get("content_md5") or f.get("contentMd5"),
                }
                for f in file_list
            ],
        }

        logger.info(
            "🔧 调用 UGCService.upload: "
            f"bucket={bucket}, resource={resource}, userId={user_id}, "
            f"files={len(file_list)}"
        )
        return self._request_triple("upload", upload_request)

    def validate(self, urls: List[str]) -> Dict[str, Any]:
        """
        调用 UGCService.validate，校验保存 URL 的有效性。

        Args:
            urls: 保存 URL 列表（bucket/resource/fileId 格式）

        Returns:
            与 ValidateFileResponse 等价的字典，通常包含 urlMap（url -> FileMeta）。
            若某 URL 无效则可能不在 urlMap 中。
        """
        if not urls:
            return {"urlMap": {}}

        validate_request = {"urls": urls}
        logger.info(
            "🔧 调用 UGCService.validate: "
            f"urls_count={len(urls)}"
        )
        return self._request_triple("validate", validate_request)

    def download_external(
        self,
        urls: List[str],
        max_age: int = 3600,
    ) -> Dict[str, Any]:
        """
        调用 UGCService.downloadExternal，获取预签名下载 URL（供外部/客户端使用）。

        Args:
            urls: 保存 URL 列表（bucket/resource/fileId 格式）
            max_age: 预签名 URL 有效期（秒）

        Returns:
            与 DownloadFileResponse 等价的字典，包含 urlList，
            每项为 { "url": save_url, "presignedUrl": 预签名下载 URL }。
        """
        if not urls:
            return {"urlList": []}

        download_request = {"urls": urls, "maxAge": max_age}
        logger.info(
            "🔧 调用 UGCService.downloadExternal: "
            f"urls_count={len(urls)}, max_age={max_age}"
        )
        return self._request_triple("downloadExternal", download_request)

    def download_internal(
        self,
        urls: List[str],
        max_age: int = 3600,
    ) -> Dict[str, Any]:
        """
        调用 UGCService.downloadInternal，获取预签名下载 URL（供内部服务使用）。

        Args:
            urls: 保存 URL 列表（bucket/resource/fileId 格式）
            max_age: 预签名 URL 有效期（秒）

        Returns:
            与 DownloadFileResponse 等价的字典，包含 urlList，
            每项为 { "url": save_url, "presignedUrl": 预签名下载 URL }。
        """
        if not urls:
            return {"urlList": []}

        download_request = {"urls": urls, "maxAge": max_age}
        logger.info(
            "🔧 调用 UGCService.downloadInternal: "
            f"urls_count={len(urls)}, max_age={max_age}"
        )
        return self._request_triple("downloadInternal", download_request)


_ugc_client: Optional[UGCClient] = None


def get_ugc_client() -> UGCClient:
    """获取 UGCClient 单例。"""
    global _ugc_client
    if _ugc_client is None:
        _ugc_client = UGCClient()
    return _ugc_client


def _self_test_upload() -> None:
    """
    简单的 upload 自测：
    - 依赖 Java 端 FileApplication 已注册到 Nacos（或配置了 UGC_TRIPLE_HOST/PORT）
    - 使用环境变量 / settings 中的默认 bucket/resource/user 进行一次轻量调用

    你可以在 .env 中新增（可选）：
        UGC_SELFTEST_BUCKET=chat
        UGC_SELFTEST_RESOURCE=document
        UGC_SELFTEST_USER_ID=1
    若未配置，则使用内置的示例值。
    """
    bucket = getattr(settings, "UGC_SELFTEST_BUCKET", "chat")
    resource = getattr(settings, "UGC_SELFTEST_RESOURCE", "document")
    user_id = int(getattr(settings, "UGC_SELFTEST_USER_ID", 1))

    # 使用一个极小的“虚拟文件”元数据，仅用于打通链路
    file_list = [
        {
            "file_name": "selftest.txt",
            "content_type": "text/plain",
            "content_length": 1,
            "content_md5": "d41d8cd98f00b204e9800998ecf8427e",  # 示例 MD5，可按需调整
        }
    ]

    logger.info(
        "🚀 开始 UGC upload 自测: "
        f"bucket={bucket}, resource={resource}, user_id={user_id}, "
        f"files={len(file_list)}"
    )

    client = get_ugc_client()
    resp = client.upload(
        bucket=bucket,
        resource=resource,
        user_id=user_id,
        max_age=3600,
        file_list=file_list,
    )

    logger.info(f"✅ UGC upload 自测成功，响应: {resp}")


if __name__ == "__main__":
    """
    允许直接运行本模块：
    1）测试 Nacos 服务发现 / Triple 直连 是否可用
    2）尝试进行一次 upload 自测调用（需 Java 端 UGCService 已正常提供 Triple 接口）
    """
    logger.info("🔍 开始测试 UGCClient Triple 发现与 upload 自测...")
    try:
        client = get_ugc_client()
        host, port = client._discover_triple_endpoint()
        logger.info(f"✅ Triple 端点发现成功: FileApplication -> {host}:{port}")
    except Exception as e:
        logger.error(f"❌ Triple 端点发现失败: {e}")
    else:
        try:
            _self_test_upload()
        except Exception as e:  # pragma: no cover - 自测失败只在联调时关注
            logger.error(f"❌ UGC upload 自测失败: {e}")
