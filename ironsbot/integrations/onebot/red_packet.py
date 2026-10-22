# SPDX-License-Identifier: MIT
"""Identify OneBot red-packet message and notice payloads without a framework."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from ironsbot.integrations.onebot.message_segments import (
    encode_onebot_message,
    onebot_message_text,
)

if TYPE_CHECKING:
    from ironsbot.integrations.onebot.connections import OneBotConnection
    from ironsbot.integrations.onebot.message_segments import OneBotSegment

_SEGMENT_TYPES = frozenset(
    {"redbag", "redpacket", "red_packet", "hongbao", "lucky_money"}
)
_BUSINESS_ID_KEYS = frozenset({"busi_id", "busiId", "business_id", "businessId"})
_RAW_MARKERS = (
    "[CQ:redbag",
    "[CQ:redpacket",
    "[CQ:red_packet",
    "[CQ:hongbao",
    "[redbag:",
    "[redpacket:",
    "[red_packet:",
    "[hongbao:",
    "[QQ红包]",
    "QQ红包",
)
_NOTICE_MARKERS = (*_RAW_MARKERS, "红包")
logger = logging.getLogger(__name__)


def _contains_marker(value: Any, markers: tuple[str, ...]) -> bool:
    if isinstance(value, str):
        return any(marker in value for marker in markers)
    if isinstance(value, Mapping):
        return any(_contains_marker(item, markers) for item in value.values())
    if isinstance(value, Iterable):
        return any(_contains_marker(item, markers) for item in value)
    return False


def _has_business_id(value: Any) -> bool:
    if isinstance(value, Mapping):
        if any(str(value.get(key) or "").strip() == "81" for key in _BUSINESS_ID_KEYS):
            return True
        return any(_has_business_id(item) for item in value.values())
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return any(_has_business_id(item) for item in value)
    return False


def is_red_packet_message(message: Sequence[OneBotSegment]) -> bool:
    return any(
        segment["type"].lower() in _SEGMENT_TYPES
        or _has_business_id(segment["data"])
        or _contains_marker(segment["data"], _RAW_MARKERS)
        for segment in message
    ) or _contains_marker(encode_onebot_message(message), _RAW_MARKERS)


def is_red_packet_payload(payload: Mapping[str, Any]) -> bool:
    subtype = str(payload.get("sub_type") or "").strip().lower()
    return (
        subtype in _SEGMENT_TYPES
        or _has_business_id(payload)
        or _contains_marker(payload, _NOTICE_MARKERS)
    )


def summarize_red_packet_message(message: Sequence[OneBotSegment]) -> str:
    for segment in message:
        if segment["type"].lower() in _SEGMENT_TYPES:
            title = str(segment["data"].get("title") or "").strip()
            return title[:80] if title else "红包消息"
    plaintext = onebot_message_text(message).strip()
    return (plaintext or encode_onebot_message(message).strip())[:80]


async def red_packet_group_name(connection: OneBotConnection, group_id: int) -> str:
    try:
        info = await connection.call_api(
            "get_group_info", group_id=group_id, no_cache=True
        )
    except Exception as error:  # noqa: BLE001 - optional protocol metadata
        logger.debug(
            "red packet group info lookup failed: error_type=%s", type(error).__name__
        )
        return ""
    return (
        str(info.get("group_name") or "").strip() if isinstance(info, Mapping) else ""
    )
