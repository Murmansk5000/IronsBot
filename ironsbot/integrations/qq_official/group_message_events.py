# SPDX-License-Identifier: MIT
"""Support Tencent's full-group-message event at the SDK boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from qqbot_agent_sdk import websocket as sdk_websocket
from qqbot_agent_sdk.dto import parse_message
from qqbot_agent_sdk.event_parser import EventParser, InboundEvent

if TYPE_CHECKING:
    from collections.abc import Mapping

GROUP_MESSAGE_CREATE = "GROUP_MESSAGE_CREATE"
GROUP_AT_MESSAGE_CREATE = "GROUP_AT_MESSAGE_CREATE"


def enable_group_message_dispatch() -> None:
    """Teach SDK 1.2.2 to forward Tencent's newer group event."""

    sdk_namespace = cast("dict[str, object]", vars(sdk_websocket))
    message_event_types = cast(
        "frozenset[object]",
        sdk_namespace["MESSAGE_EVENT_TYPES"],
    )
    if GROUP_MESSAGE_CREATE in message_event_types:
        return
    sdk_namespace["MESSAGE_EVENT_TYPES"] = frozenset(
        (*message_event_types, GROUP_MESSAGE_CREATE)
    )


def parse_message_event(
    event_type: str,
    raw: Mapping[str, object],
) -> InboundEvent | None:
    """Parse SDK-supported events plus the full-group-message event."""

    payload = dict(raw)
    if event_type != GROUP_MESSAGE_CREATE:
        return EventParser.parse(event_type, payload)

    message = parse_message(payload)
    if not message.group_openid or not message.author.member_openid:
        return None
    return InboundEvent(
        event_type=event_type,
        chat_id=message.group_openid,
        user_id=message.author.member_openid,
        chat_scope="group",
        content=message.content.strip(),
        message_id=message.id,
        timestamp=message.timestamp,
        message_type=message.message_type,
        attachments=message.attachments,
        msg_elements=message.msg_elements,
        raw=payload,
    )


def message_event_family(event_type: str) -> str:
    """Collapse both group delivery variants for duplicate suppression."""

    if event_type in {GROUP_MESSAGE_CREATE, GROUP_AT_MESSAGE_CREATE}:
        return "GROUP_MESSAGE"
    return event_type
