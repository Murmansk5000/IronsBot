from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from ironsbot.services.bilibili.parser import (
    dynamic_body_hydration_reason,
    dynamic_content,
    dynamic_id,
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
    """Fill a missing or truncated feed item with its Opus-style detail item."""

    item_id = dynamic_id(item)
    hydration_reason = dynamic_body_hydration_reason(item)
    if hydration_reason is None or not item_id:
        return item

    list_content_length = len(dynamic_content(item))
    logger.info(
        "Bilibili dynamic detail hydration requested: id=%s reason=%s "
        "list_length=%s",
        item_id,
        hydration_reason,
        list_content_length,
    )

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
    elif (
        (author_mid := item_author_mid(item))
        and item_author_mid(resolved) != author_mid
    ):
        logger.warning(
            "Bilibili dynamic detail author mismatch: id=%s expected=%s",
            item_id,
            author_mid,
        )
    else:
        detail_content_length = len(dynamic_content(resolved))
        detail_reason = dynamic_body_hydration_reason(resolved)
        if detail_reason is None and detail_content_length > list_content_length:
            logger.info(
                "Bilibili dynamic detail hydration completed: id=%s reason=%s "
                "list_length=%s detail_length=%s",
                item_id,
                hydration_reason,
                list_content_length,
                detail_content_length,
            )
            return resolved
        logger.warning(
            "Bilibili dynamic detail hydration rejected: id=%s reason=%s "
            "list_length=%s detail_length=%s detail_reason=%s",
            item_id,
            hydration_reason,
            list_content_length,
            detail_content_length,
            detail_reason,
        )
    return item
