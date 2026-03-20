# -*- coding: utf-8 -*-
"""
UGC 文件服务客户端（Nacos + Dubbo Triple(JSON)）

目标：
- 通过 Nacos 发现 FileApplication（Java 侧 Dubbo 应用，协议为 tri）
- 使用 HTTP/2 h2c 直接以 JSON 形式调用 UGCService.* 接口（免 IDL）

说明：
- Java 端需开启 Dubbo 3 Triple 协议，接口路径形如：
  /com.tyqy.file.api.dubbo.UGCService/upload
- 底层传输由 BaseDubboTripleClient 提供，本模块只实现业务方法。
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from ty_mem_agent.config.settings import settings
from ty_mem_agent.server.dubbo_triple_base import BaseDubboTripleClient, BaseDubboTripleConfig


def _build_ugc_config() -> BaseDubboTripleConfig:
    _nacos_addrs = (settings.NACOS_SERVER_ADDRESSES or "localhost:8848").split(",")
    return BaseDubboTripleConfig(
        nacos_addr=_nacos_addrs[0].strip(),
        nacos_namespace=settings.NACOS_NAMESPACE or "public",
        application_name="FileApplication",
        interface_name="com.tyqy.file.api.dubbo.UGCService",
        direct_host=getattr(settings, "UGC_TRIPLE_HOST", None),
        direct_port=getattr(settings, "UGC_TRIPLE_PORT", None),
        use_tls=bool(getattr(settings, "UGC_TRIPLE_USE_TLS", False)),
        timeout=int(getattr(settings, "UGC_TRIPLE_TIMEOUT_SECONDS", 30)),
    )


class UGCClient(BaseDubboTripleClient):
    """基于 Nacos + Dubbo Triple(JSON) 的 UGC 文件服务客户端"""

    def __init__(self) -> None:
        super().__init__(_build_ugc_config())

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
        logger.info(
            f"🔧 调用 UGCService.upload: "
            f"bucket={bucket}, resource={resource}, userId={user_id}, "
            f"files={len(file_list)}"
        )
        return self._request_triple(
            "upload",
            {
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
            },
        )

    def validate(self, urls: List[str]) -> Dict[str, Any]:
        """
        调用 UGCService.validate，校验保存 URL 的有效性。

        Args:
            urls: 保存 URL 列表（bucket/resource/fileId 格式）
        """
        if not urls:
            return {"urlMap": {}}
        logger.info(f"🔧 调用 UGCService.validate: urls_count={len(urls)}")
        return self._request_triple("validate", {"urls": urls})

    def download_external(
        self,
        urls: List[str],
        max_age: int = 3600,
    ) -> Dict[str, Any]:
        """
        调用 UGCService.downloadExternal，获取预签名下载 URL（供外部/客户端使用）。

        Args:
            urls: 保存 URL 列表
            max_age: 预签名 URL 有效期（秒）
        """
        if not urls:
            return {"urlList": []}
        logger.info(
            f"🔧 调用 UGCService.downloadExternal: "
            f"urls_count={len(urls)}, max_age={max_age}"
        )
        return self._request_triple("downloadExternal", {"urls": urls, "maxAge": max_age})

    def download_internal(
        self,
        urls: List[str],
        max_age: int = 3600,
    ) -> Dict[str, Any]:
        """
        调用 UGCService.downloadInternal，获取预签名下载 URL（供内部服务使用）。

        Args:
            urls: 保存 URL 列表
            max_age: 预签名 URL 有效期（秒）
        """
        if not urls:
            return {"urlList": []}
        logger.info(
            f"🔧 调用 UGCService.downloadInternal: "
            f"urls_count={len(urls)}, max_age={max_age}"
        )
        return self._request_triple("downloadInternal", {"urls": urls, "maxAge": max_age})


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

    file_list = [
        {
            "file_name": "selftest.txt",
            "content_type": "text/plain",
            "content_length": 1,
            "content_md5": "d41d8cd98f00b204e9800998ecf8427e",
        }
    ]

    logger.info(
        f"🚀 开始 UGC upload 自测: "
        f"bucket={bucket}, resource={resource}, user_id={user_id}, "
        f"files={len(file_list)}"
    )
    resp = get_ugc_client().upload(
        bucket=bucket,
        resource=resource,
        user_id=user_id,
        max_age=3600,
        file_list=file_list,
    )
    logger.info(f"✅ UGC upload 自测成功，响应: {resp}")


if __name__ == "__main__":
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
        except Exception as e:
            logger.error(f"❌ UGC upload 自测失败: {e}")
