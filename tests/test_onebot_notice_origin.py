from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.integrations.onebot import notice_origin
from ironsbot.services.identity_principals import IdentityPrincipalService


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
async def test_official_notice_uses_trusted_links_and_napcat_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    bot.get_group_info.return_value = {"group_name": "测试群"}
    bot.get_group_member_info.return_value = {"card": "群昵称", "nickname": "QQ昵称"}
    monkeypatch.setattr(notice_origin, "get_bots", lambda: {"999": bot})

    result = await notice_origin.resolve_notice_origin(
        _context(Platform.QQ_OFFICIAL), principals
    )

    assert "群：测试群（QQ群：456）" in result
    assert "用户：QQ昵称（QQ：789）" in result
    bot.get_group_info.assert_awaited_once()
    bot.get_group_member_info.assert_awaited_once()


@pytest.mark.asyncio
async def test_unlinked_official_notice_does_not_guess_qq_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notice_origin, "get_bots", dict)
    result = await notice_origin.resolve_notice_origin(
        _context(Platform.QQ_OFFICIAL, name="公开昵称"), IdentityPrincipalService()
    )
    assert "群：QQ 群号未关联" in result
    assert "用户：公开昵称" in result
    assert "QQ：789" not in result


@pytest.mark.asyncio
async def test_onebot_notice_keeps_ids_when_napcat_name_lookup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = AsyncMock()
    bot.self_id = "999"
    bot.get_group_info.side_effect = RuntimeError("offline")
    bot.get_group_member_info.side_effect = RuntimeError("offline")
    bot.get_stranger_info.side_effect = RuntimeError("offline")
    monkeypatch.setattr(notice_origin, "get_bots", lambda: {"999": bot})

    result = await notice_origin.resolve_notice_origin(
        _context(Platform.ONEBOT), IdentityPrincipalService()
    )

    assert "群：QQ群 456（名称暂不可用）" in result
    assert "用户：QQ 789" in result
