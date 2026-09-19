from __future__ import annotations

from typing import TYPE_CHECKING

from qqbot_agent_sdk import websocket as sdk_websocket

from ironsbot.integrations.qq_official.group_message_events import (
    GROUP_AT_MESSAGE_CREATE,
    GROUP_MESSAGE_CREATE,
    enable_group_message_dispatch,
    message_event_family,
    parse_message_event,
)

if TYPE_CHECKING:
    import pytest


def test_full_group_event_is_registered_with_sdk_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sdk_websocket, "MESSAGE_EVENT_TYPES", frozenset())

    enable_group_message_dispatch()
    enable_group_message_dispatch()

    assert frozenset({GROUP_MESSAGE_CREATE}) == vars(sdk_websocket)[
        "MESSAGE_EVENT_TYPES"
    ]


def test_full_group_event_parser_preserves_unaddressed_content() -> None:
    event = parse_message_event(
        GROUP_MESSAGE_CREATE,
        {
            "id": "message-id",
            "content": "@另一位成员 刻印1",
            "timestamp": "2026-09-19T12:00:00+08:00",
            "group_openid": "group-openid",
            "author": {"member_openid": "member-openid"},
            "mentions": [{"member_openid": "other-member"}],
        },
    )

    assert event is not None
    assert event.event_type == GROUP_MESSAGE_CREATE
    assert event.chat_scope == "group"
    assert event.chat_id == "group-openid"
    assert event.user_id == "member-openid"
    assert event.content == "@另一位成员 刻印1"


def test_group_delivery_variants_share_one_deduplication_family() -> None:
    assert message_event_family(GROUP_MESSAGE_CREATE) == "GROUP_MESSAGE"
    assert message_event_family(GROUP_AT_MESSAGE_CREATE) == "GROUP_MESSAGE"
    assert message_event_family("C2C_MESSAGE_CREATE") == "C2C_MESSAGE_CREATE"
