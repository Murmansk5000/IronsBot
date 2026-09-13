from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx
import pytest
from qqbot_agent_sdk.event_parser import EventParser

from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.qq_official.identity import qq_official_incoming_message
from ironsbot.integrations.qq_official.runtime import (
    QQOfficialRuntime,
    QQOfficialRuntimeAccount,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_official_sdk_parser_feeds_opaque_group_identity() -> None:
    raw = {
        "id": "message-id",
        "content": "@babyQ 帮助",
        "timestamp": "2026-09-14T00:00:00+08:00",
        "group_openid": "group-openid",
        "author": {
            "member_openid": "member-openid",
            "member_role": "admin",
        },
    }

    event = EventParser.parse("GROUP_AT_MESSAGE_CREATE", raw)

    assert event is not None
    incoming = qq_official_incoming_message(event, account_id="app-id")
    assert incoming.text == "帮助"
    assert incoming.actor == ActorRef(
        Platform.QQ_OFFICIAL,
        "member-openid",
        "member",
        "group-openid",
        "app-id",
    )
    assert incoming.conversation == ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "group-openid",
        "app-id",
    )
    assert incoming.group_role == "admin"


def test_runtime_keeps_clients_isolated_by_app_id(tmp_path: Path) -> None:
    async def run() -> None:
        async with httpx.AsyncClient() as client:
            runtime = QQOfficialRuntime(
                (
                    QQOfficialRuntimeAccount("app-a", "secret-a"),
                    QQOfficialRuntimeAccount("app-b", "secret-b"),
                ),
                http_client=client,
                session_root=tmp_path,
            )

            assert runtime.account_ids == ("app-a", "app-b")
            assert runtime.sender("app-a") is not runtime.sender("app-b")
            assert runtime.sender("missing") is None

    asyncio.run(run())


def test_runtime_rejects_duplicate_app_ids(tmp_path: Path) -> None:
    async def run() -> None:
        async with httpx.AsyncClient() as client:
            with pytest.raises(ValueError, match="duplicate QQ Official AppID"):
                QQOfficialRuntime(
                    (
                        QQOfficialRuntimeAccount("same-app", "secret-a"),
                        QQOfficialRuntimeAccount("same-app", "secret-b"),
                    ),
                    http_client=client,
                    session_root=tmp_path,
                )

    asyncio.run(run())
