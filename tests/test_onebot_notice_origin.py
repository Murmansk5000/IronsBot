from __future__ import annotations

from dataclasses import dataclass, field, replace
from unittest.mock import AsyncMock

import pytest

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import ExecutionIdentity
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.integrations.onebot import notice_origin
from ironsbot.integrations.onebot.connections import OneBotConnections
from ironsbot.services.identity_principals import IdentityPrincipalService


@dataclass
class _Connection:
    self_id: str
    fail_member: bool = False
    calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    async def call_api(self, api: str, **data: object) -> object:
        self.calls.append((api, data))
        if api == "get_group_info":
            return {"group_name": "group label"}
        if api == "get_group_member_info":
            if self.fail_member:
                raise LookupError
            return {"nickname": "member label", "card": "card label"}
        if api == "get_stranger_info":
            return {"nickname": "user label"}
        raise AssertionError(api)


def _context(platform: Platform, *, name: str = "") -> MessageInputContext:
    account_id = "123" if platform is Platform.QQ_OFFICIAL else None
    group = ConversationRef(
        platform, "group", "group-openid" if account_id else "456", account_id
    )
    actor = ActorRef(
        platform,
        "member-openid" if account_id else "789",
        "member",
        group.id,
        account_id,
    )
    return MessageInputContext(
        IncomingMessageRef(platform, actor, group, "message", "query"),
        mentions_bot=True,
        actor_display_name=name,
    )


@pytest.mark.asyncio
async def test_official_notice_uses_trusted_links_and_napcat_names() -> None:
    principals = IdentityPrincipalService()
    principals.register_configured_group(
        alias="example",
        onebot_group_id="456",
        official_endpoints=(("123", "group-openid"),),
    )
    principals.register_configured_actor(
        alias="sender",
        onebot_qq_id="789",
        official_endpoints=(("123", "member-openid"),),
    )
    bot = AsyncMock()
    bot.self_id = "999"
    bot.call_api.side_effect = [
        {"group_name": "测试群"},
        {"card": "群昵称", "nickname": "QQ昵称"},
    ]
    connections = OneBotConnections()
    connections.connect(bot)

    result = await notice_origin.resolve_notice_origin(
        _context(Platform.QQ_OFFICIAL), principals, connections
    )

    assert "群：测试群（QQ群：456）" in result
    assert "用户：QQ昵称（QQ：789）" in result
    assert [call.args[0] for call in bot.call_api.await_args_list] == [
        "get_group_info",
        "get_group_member_info",
    ]


@pytest.mark.asyncio
async def test_unlinked_official_notice_does_not_guess_qq_ids() -> None:
    result = await notice_origin.resolve_notice_origin(
        _context(Platform.QQ_OFFICIAL, name="公开昵称"),
        IdentityPrincipalService(),
        OneBotConnections(),
    )
    assert "群：QQ 群号未关联" in result
    assert "用户：公开昵称" in result
    assert "QQ：789" not in result


@pytest.mark.asyncio
async def test_onebot_notice_keeps_ids_when_napcat_name_lookup_fails() -> None:
    bot = AsyncMock()
    bot.self_id = "999"
    bot.call_api.side_effect = RuntimeError("offline")
    connections = OneBotConnections()
    connections.connect(bot)

    result = await notice_origin.resolve_notice_origin(
        _context(Platform.ONEBOT), IdentityPrincipalService(), connections
    )

    assert "群：QQ群 456（名称暂不可用）" in result
    assert "用户：QQ 789" in result


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_member", [False, True])
async def test_origin_queries_use_only_the_minimal_connection_port(
    *, fail_member: bool
) -> None:
    connection = _Connection("999", fail_member=fail_member)
    connections = OneBotConnections()
    connections.connect(connection)
    context = replace(
        _context(Platform.ONEBOT),
        execution_identity=ExecutionIdentity(Platform.ONEBOT, "999"),
    )
    result = await notice_origin.resolve_notice_origin(
        context, IdentityPrincipalService(), connections
    )
    assert "群：group label（QQ群：456）" in result
    expected_name = "user label" if fail_member else "member label"
    assert f"用户：{expected_name}（QQ：789）" in result
    assert connection.calls[:2] == [
        ("get_group_info", {"group_id": 456, "no_cache": False}),
        ("get_group_member_info", {"group_id": 456, "user_id": 789, "no_cache": False}),
    ]
    assert connection.calls[2:] == (
        [("get_stranger_info", {"user_id": 789, "no_cache": False})]
        if fail_member
        else []
    )


@pytest.mark.asyncio
async def test_origin_prefers_receiving_connection_without_sending_on_another() -> None:
    preferred, other = _Connection("999"), _Connection("888")
    connections = OneBotConnections()
    connections.connect(other)
    connections.connect(preferred)
    context = replace(
        _context(Platform.ONEBOT),
        execution_identity=ExecutionIdentity(Platform.ONEBOT, "999"),
    )
    await notice_origin.resolve_notice_origin(
        context, IdentityPrincipalService(), connections
    )
    assert [api for api, _ in preferred.calls] == [
        "get_group_info",
        "get_group_member_info",
    ]
    assert other.calls == []
