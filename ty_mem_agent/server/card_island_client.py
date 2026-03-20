# -*- coding: utf-8 -*-
"""
卡片岛服务客户端（Nacos + Dubbo Triple(JSON)）

目标：
- 通过 Nacos 发现 CardIslandApplication（Java 侧 Dubbo 应用，协议为 tri）
- 调用 CardIslandDubboService 的 publish / close / delete 接口

接口路径：
  /com.tyqy.cardisland.api.dubbo.CardIslandDubboService/publish
  /com.tyqy.cardisland.api.dubbo.CardIslandDubboService/close
  /com.tyqy.cardisland.api.dubbo.CardIslandDubboService/delete
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from ty_mem_agent.config.settings import settings
from ty_mem_agent.server.dubbo_triple_base import BaseDubboTripleClient, BaseDubboTripleConfig


def _build_card_island_config() -> BaseDubboTripleConfig:
    _nacos_addrs = (settings.NACOS_SERVER_ADDRESSES or "localhost:8848").split(",")
    return BaseDubboTripleConfig(
        nacos_addr=_nacos_addrs[0].strip(),
        nacos_namespace=settings.NACOS_NAMESPACE or "public",
        application_name="CardIslandApplication",
        interface_name="com.tyqy.cardisland.api.dubbo.CardIslandDubboService",
        direct_host=getattr(settings, "CARD_ISLAND_TRIPLE_HOST", None),
        direct_port=getattr(settings, "CARD_ISLAND_TRIPLE_PORT", None),
        use_tls=bool(getattr(settings, "CARD_ISLAND_TRIPLE_USE_TLS", False)),
        timeout=int(getattr(settings, "CARD_ISLAND_TRIPLE_TIMEOUT_SECONDS", 30)),
    )


class CardIslandClient(BaseDubboTripleClient):
    """基于 Nacos + Dubbo Triple(JSON) 的卡片岛服务客户端"""

    def __init__(self) -> None:
        super().__init__(_build_card_island_config())

    def publish(
        self,
        user_id: int,
        events: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        推送卡片事件给用户。

        Args:
            user_id: 目标用户 ID
            events:  卡片事件列表，每项包含：
                       - type (str)：卡片类型，如 "weather"
                       - detail (str)：描述字符串或结构化 JSON 序列化后的字符串

        Returns:
            包含 events 列表的字典，每项含 id / userId / createTime / type / detail。
            其中 id 即卡片岛生成的 eventId，可用于后续 close / delete 调用。
        """
        logger.info(
            f"🔧 调用 CardIslandDubboService.publish: "
            f"userId={user_id}, events={len(events)}"
        )
        return self._request_triple(
            "publish",
            {
                "userId": user_id,
                "events": [
                    {
                        "type": e.get("type"),
                        "detail": e.get("detail"),
                    }
                    for e in events
                ],
            },
        )

    def close(
        self,
        user_id: int,
        event_ids: List[int],
    ) -> Dict[str, Any]:
        """
        关闭（隐藏）指定的卡片事件。

        Args:
            user_id:   用户 ID
            event_ids: 要关闭的 eventId 列表（由 publish 返回）
        """
        logger.info(
            f"🔧 调用 CardIslandDubboService.close: "
            f"userId={user_id}, eventIds={event_ids}"
        )
        return self._request_triple(
            "close",
            {"userId": user_id, "eventIds": event_ids},
        )

    def delete(
        self,
        user_id: int,
        event_ids: List[int],
    ) -> Dict[str, Any]:
        """
        删除指定的卡片事件。

        Args:
            user_id:   用户 ID
            event_ids: 要删除的 eventId 列表（由 publish 返回）
        """
        logger.info(
            f"🔧 调用 CardIslandDubboService.delete: "
            f"userId={user_id}, eventIds={event_ids}"
        )
        return self._request_triple(
            "delete",
            {"userId": user_id, "eventIds": event_ids},
        )


_card_island_client: Optional[CardIslandClient] = None


def get_card_island_client() -> CardIslandClient:
    """获取 CardIslandClient 单例。"""
    global _card_island_client
    if _card_island_client is None:
        _card_island_client = CardIslandClient()
    return _card_island_client


if __name__ == "__main__":
    logger.info("🔍 开始测试 CardIslandClient Triple 端点发现...")
    try:
        client = get_card_island_client()
        host, port = client._discover_triple_endpoint()
        logger.info(f"✅ Triple 端点发现成功: CardIslandApplication -> {host}:{port}")
    except Exception as e:
        logger.error(f"❌ Triple 端点发现失败: {e}")
