# SPDX-License-Identifier: MIT
"""Forward Tencent events missing from qqbot-agent-sdk 1.2.2."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from qqbot_agent_sdk import websocket as sdk_websocket
from qqbot_agent_sdk.dto import parse_message
from qqbot_agent_sdk.event_parser import EventParser, InboundEvent

if TYPE_CHECKING:
    from collections.abc import Mapping

GROUP_MESSAGE_CREATE = "GROUP_MESSAGE_CREATE"
GROUP_AT_MESSAGE_CREATE = "GROUP_AT_MESSAGE_CREATE"
RECIPIENT_STATE_EVENT_TYPES = frozenset(
    {
        "C2C_MSG_RECEIVE",
        "C2C_MSG_REJECT",
        "FRIEND_ADD",
        "FRIEND_DEL",
        "GROUP_ADD_ROBOT",
        "GROUP_DEL_ROBOT",
        "GROUP_MSG_RECEIVE",
        "GROUP_MSG_REJECT",
    }
)


def enable_qq_event_dispatch() -> None:
    """Teach SDK 1.2.2 to forward current message and recipient events."""

    sdk_namespace = cast("dict[str, object]", vars(sdk_websocket))
    message_event_types = cast(
        "frozenset[object]",
        sdk_namespace["MESSAGE_EVENT_TYPES"],
    )
    required = frozenset({GROUP_MESSAGE_CREATE, *RECIPIENT_STATE_EVENT_TYPES})
    if required <= message_event_types:
        return
    sdk_namespace["MESSAGE_EVENT_TYPES"] = message_event_types | required


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


def is_recipient_state_event(event_type: str) -> bool:
    """Return whether an event updates proactive-delivery eligibility."""

    return event_type in RECIPIENT_STATE_EVENT_TYPES
