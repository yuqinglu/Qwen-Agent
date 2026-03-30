# -*- coding: utf-8 -*-
"""Environment configuration (pydantic-settings)."""

import json
from functools import lru_cache
from typing import Any, Dict, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Server
    host: str = Field(default="0.0.0.0", alias="ADAPTER_HOST")
    port: int = Field(default=8090, alias="ADAPTER_PORT")

    # ty-mem-agent → adapter
    adapter_api_key: str = Field(default="", alias="ADAPTER_API_KEY")

    # HMAC for adapter → ty-mem-agent (must match ty_mem_agent OPENCLAW_CALLBACK_SECRET)
    ty_mem_callback_hmac_secret: str = Field(default="", alias="TY_MEM_CALLBACK_HMAC_SECRET")

    # Public origin of this adapter (no trailing slash). Cron delivery.webhook "to" is
    # {adapter_public_base_url}/openclaw-adapter/internal/openclaw/webhook
    adapter_public_base_url: str = Field(
        default="http://127.0.0.1:8090", alias="ADAPTER_PUBLIC_BASE_URL"
    )

    # OpenClaw Gateway → adapter inbound webhook verification (Bearer)
    openclaw_webhook_bearer_token: str = Field(default="", alias="OPENCLAW_WEBHOOK_BEARER_TOKEN")

    # --- Gateway backends ---
    gateway_mode: str = Field(default="stub", alias="ADAPTER_GATEWAY_MODE")

    gateway_http_url: Optional[str] = Field(default=None, alias="ADAPTER_GATEWAY_HTTP_URL")
    gateway_http_token: str = Field(default="", alias="ADAPTER_GATEWAY_HTTP_TOKEN")
    # Optional DELETE URL template for cancel, {job_id} placeholder
    gateway_http_remove_url: Optional[str] = Field(default=None, alias="ADAPTER_GATEWAY_HTTP_REMOVE_URL")

    # {body} = JSON object literal，与 OpenClaw cron.add 的 params 一致（见官方 Cron 文档），嵌入 tools/invoke
    # 开源 Gateway 实测形态：{"tool":"cron","action":"add","args":{...}}（非 cron.add 单工具名）
    gateway_http_body_template: str = Field(
        default='{"tool":"cron","action":"add","args":{body}}',
        alias="ADAPTER_GATEWAY_HTTP_BODY_TEMPLATE",
    )

    gateway_http_job_id_path: str = Field(
        default="result.jobId", alias="ADAPTER_GATEWAY_HTTP_JOB_ID_PATH"
    )

    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/adapter.db",
        alias="ADAPTER_DATABASE_URL",
    )

    # Dev-only: allow POST /openclaw-adapter/internal/dev/simulate-callback
    dev_endpoints_enabled: bool = Field(default=False, alias="ADAPTER_DEV_ENDPOINTS")

    # --- Nacos（与 ty_mem_agent 相同环境变量名，便于统一部署）---
    nacos_enabled: bool = Field(default=False, alias="NACOS_ENABLED")
    nacos_server_addresses: str = Field(default="localhost:8848", alias="NACOS_SERVER_ADDRESSES")
    nacos_namespace: Optional[str] = Field(default=None, alias="NACOS_NAMESPACE")
    nacos_username: Optional[str] = Field(default=None, alias="NACOS_USERNAME")
    nacos_password: Optional[str] = Field(default=None, alias="NACOS_PASSWORD")
    nacos_service_name: str = Field(default="openclaw-adapter", alias="NACOS_SERVICE_NAME")
    nacos_group_name: Optional[str] = Field(default=None, alias="NACOS_GROUP_NAME")
    # 可选：合并到 Nacos 实例 metadata 的 JSON 对象（如 {"env":"prod","team":"x"}）
    nacos_metadata_extra_json: Optional[str] = Field(default=None, alias="NACOS_METADATA_EXTRA_JSON")

    def parsed_nacos_metadata_extra(self) -> Dict[str, Any]:
        if not self.nacos_metadata_extra_json or not self.nacos_metadata_extra_json.strip():
            return {}
        try:
            data = json.loads(self.nacos_metadata_extra_json)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


@lru_cache
def get_settings() -> Settings:
    return Settings()
