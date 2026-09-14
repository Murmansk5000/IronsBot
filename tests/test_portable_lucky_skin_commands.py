from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.portable_lucky_skin_commands import (
    build_portable_lucky_skin_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.seer.lucky_skin_window import (
    LuckySkinWatchItem,
    LuckySkinWindowResult,
)
from ironsbot.services.seer.pet_query import PetImageSelection
from ironsbot.services.seer.query_result import QueryChoice, QueryReply, QueryResult

if TYPE_CHECKING:
    from ironsbot.services.identity_linking import IdentityLinkingService
    from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowService
    from ironsbot.services.seer.pet_query import PetQueryService

_Operation = Callable[[str, MessageInputContext], Awaitable[OutboundMessage]]


def _context(text: str = "橱窗") -> MessageInputContext:
    actor = ActorRef(
        Platform.QQ_OFFICIAL,
        "member-openid",
        "member",
        "group-openid",
        "official-app",
    )
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "group-openid",
        "official-app",
    )
    return MessageInputContext(
        IncomingMessageRef(
            Platform.QQ_OFFICIAL,
            actor,
            conversation,
            f"message-{text}",
            text,
        ),
        mentions_bot=True,
    )


def _text(message: OutboundMessage) -> str:
    part = message.parts[0]
    assert isinstance(part, TextPart)
    return part.text


def _dependencies(
    *, linked: bool = True
) -> tuple[
    Mock,
    Mock,
    Mock,
    PortableQuerySessions,
    ActorRef,
]:
    onebot = ActorRef(Platform.ONEBOT, "1621582661")
    service = Mock()
    pet = Mock()
    identity = Mock()
    identity.linked_onebot_actor = AsyncMock(return_value=onebot if linked else None)
    return service, pet, identity, PortableQuerySessions(), onebot


def _operations(
    service: Mock,
    pet: Mock,
    identity: Mock,
    sessions: PortableQuerySessions,
) -> dict[str, _Operation]:
    return cast(
        "dict[str, _Operation]",
        build_portable_lucky_skin_operations(
            cast("LuckySkinWindowService", service),
            cast("PetQueryService", pet),
            cast("IdentityLinkingService", identity),
            sessions,
        ),
    )


@pytest.mark.asyncio
async def test_unlinked_official_identity_is_not_guessed() -> None:
    service, pet, identity, sessions, _ = _dependencies(linked=False)
    operations = _operations(service, pet, identity, sessions)

    reply = await operations["seer.lucky_skin_window.query"]("橱窗", _context())

    assert "关联官方账号" in _text(reply)
    service.cached_for_actor.assert_not_called()


@pytest.mark.asyncio
async def test_cached_query_uses_linked_account_and_skin_buttons() -> None:
    service, pet, identity, sessions, onebot = _dependencies()
    result = LuckySkinWindowResult("2026-09-15", 90001, (), from_cache=True)
    choice = QueryChoice(
        "测试皮肤",
        "101 / 1400101",
        PetImageSelection(1400101, "测试皮肤", skin_id=101),
    )
    service.cached_for_actor.return_value = result
    service.detail_choices.return_value = (choice,)
    service.result_message = AsyncMock(
        return_value=OutboundMessage.from_text("【幸运橱窗】")
    )
    pet.select_image = AsyncMock(
        return_value=QueryResult(reply=QueryReply(text="皮肤详情"))
    )
    operations = _operations(service, pet, identity, sessions)
    context = _context()

    menu = await operations["seer.lucky_skin_window.query"]("橱窗", context)
    selected = await sessions.select("1", context)

    service.cached_for_actor.assert_called_once_with(onebot)
    assert menu.prompt is not None
    assert menu.prompt.choices[0].label == "测试皮肤"
    assert selected is not None
    assert _text(selected) == "皮肤详情"


@pytest.mark.asyncio
async def test_uncached_query_runs_only_after_confirmation() -> None:
    service, pet, identity, sessions, onebot = _dependencies()
    result = LuckySkinWindowResult("2026-09-15", 90001, (), from_cache=False)
    service.cached_for_actor.return_value = None
    service.check_for_actor = AsyncMock(return_value=result)
    service.detail_choices.return_value = ()
    service.result_message = AsyncMock(
        return_value=OutboundMessage.from_text("【幸运橱窗】")
    )
    operations = _operations(service, pet, identity, sessions)
    context = _context()

    confirmation = await operations["seer.lucky_skin_window.query"](
        "橱窗", context
    )
    service.check_for_actor.assert_not_awaited()
    result_message = await sessions.select("1", context)

    assert confirmation.prompt is not None
    assert tuple(choice.label for choice in confirmation.prompt.choices) == (
        "确认查询",
        "取消查询",
        "退出",
    )
    service.check_for_actor.assert_awaited_once_with(onebot)
    assert result_message is not None
    assert _text(result_message) == "【幸运橱窗】"


@pytest.mark.asyncio
async def test_watch_operations_reuse_linked_onebot_preferences() -> None:
    service, pet, identity, sessions, onebot = _dependencies()
    item = LuckySkinWatchItem(101, 1400101, "测试皮肤")
    service.watch_list_message.return_value = "关注列表"
    service.resolve_watch_candidates.return_value = (item,)
    service.watch_change_message.side_effect = (
        lambda _actor, selected, *, watched: (
            f"{'已关注' if watched else '已取消关注'}：{selected.name}"
        )
    )
    service.watch_clear_message.return_value = "已清空关注皮肤。"
    service.watch_reset_message.return_value = "已恢复 TOML 初始关注列表。"
    operations = _operations(service, pet, identity, sessions)

    replies = (
        await operations["seer.lucky_skin_window.watch.list"](
            "关注橱窗", _context("关注橱窗")
        ),
        await operations["seer.lucky_skin_window.watch.add"](
            "关注橱窗测试", _context("关注橱窗测试")
        ),
        await operations["seer.lucky_skin_window.watch.remove"](
            "取消关注橱窗测试", _context("取消关注橱窗测试")
        ),
        await operations["seer.lucky_skin_window.watch.clear"](
            "清空关注橱窗", _context("清空关注橱窗")
        ),
        await operations["seer.lucky_skin_window.watch.reset"](
            "重置关注橱窗", _context("重置关注橱窗")
        ),
    )

    assert tuple(_text(reply) for reply in replies) == (
        "关注列表",
        "已关注：测试皮肤",
        "已取消关注：测试皮肤",
        "已清空关注皮肤。",
        "已恢复 TOML 初始关注列表。",
    )
    assert service.resolve_watch_candidates.call_args_list[0].args == (
        onebot,
        "测试",
    )


@pytest.mark.asyncio
async def test_ambiguous_watch_change_uses_named_selection_buttons() -> None:
    service, pet, identity, sessions, onebot = _dependencies()
    candidates = (
        LuckySkinWatchItem(101, 1400101, "皮肤甲"),
        LuckySkinWatchItem(102, 1400102, "皮肤乙"),
    )
    service.resolve_watch_candidates.return_value = candidates
    service.watch_change_message.return_value = "已关注：皮肤乙"
    operations = _operations(service, pet, identity, sessions)
    context = _context("关注橱窗皮肤")

    menu = await operations["seer.lucky_skin_window.watch.add"](
        "关注橱窗皮肤", context
    )
    selected = await sessions.select("2", context)

    assert menu.prompt is not None
    assert tuple(choice.label for choice in menu.prompt.choices) == (
        "皮肤甲",
        "皮肤乙",
        "退出",
    )
    service.watch_change_message.assert_called_once_with(
        onebot,
        candidates[1],
        watched=True,
    )
    assert selected is not None
    assert _text(selected) == "已关注：皮肤乙"
