from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from ironsbot.services.bilibili.parser import (
    dynamic_id,
    has_dynamic_body,
    item_author_mid,
)

logger = logging.getLogger(__name__)
HTTP_OK = 200


class DynamicDetailResponse(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def data(self) -> object: ...


DynamicDetailFetcher = Callable[[str, str], Awaitable[DynamicDetailResponse]]


def detail_item(response: DynamicDetailResponse) -> dict[str, Any] | None:
    payload = response.data if isinstance(response.data, Mapping) else {}
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
    item = data.get("item") if isinstance(data, Mapping) else None
    return item if isinstance(item, dict) else None


async def hydrate_dynamic_item(
    item: dict[str, Any],
    *,
    cookie: str,
    fetch_detail: DynamicDetailFetcher,
) -> dict[str, Any]:
    """Fill an otherwise textless feed item with its Opus-style detail item."""

    item_id = dynamic_id(item)
    if has_dynamic_body(item) or not item_id:
        return item

    try:
        response = await fetch_detail(cookie, item_id)
    except Exception:
        logger.exception("Bilibili dynamic detail request failed: %s", item_id)
        return item

    payload = response.data if isinstance(response.data, Mapping) else {}
    api_code = payload.get("code") if isinstance(payload, Mapping) else None
    resolved = detail_item(response)
    if response.status_code != HTTP_OK or api_code != 0 or resolved is None:
        logger.warning(
            "Bilibili dynamic detail unavailable: id=%s http=%s code=%s",
            item_id,
            response.status_code,
            api_code,
        )
        return item
    if dynamic_id(resolved) != item_id:
        logger.warning("Bilibili dynamic detail ID mismatch: expected=%s", item_id)
        return item
    author_mid = item_author_mid(item)
    if author_mid and item_author_mid(resolved) != author_mid:
        logger.warning(
            "Bilibili dynamic detail author mismatch: id=%s expected=%s",
            item_id,
            author_mid,
        )
        return item
    return resolved
