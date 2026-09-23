from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.player_references import PlayerReferenceChoice
from ironsbot.services.identity_link_store import OfficialIdentity
from ironsbot.services.identity_principals import IdentityPrincipalService
from ironsbot.services.portable_lucky_skin_commands import (
    build_portable_lucky_skin_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.seer.lucky_skin_window import (
    LuckySkinQuery,
    LuckySkinWatchItem,
    LuckySkinWindowAccessError,
    LuckySkinWindowResult,
)
from ironsbot.services.seer.pet_query import PetImageSelection
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.query_result import QueryChoice, QueryReply, QueryResult

if TYPE_CHECKING:
    from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowService
    from ironsbot.services.seer.pet_query import PetQueryService

_Operation = Callable[[str, MessageInputContext], Awaitable[OutboundMessage]]


def _context(
    text: str = "橱窗",
    *,
    platform: Platform = Platform.QQ_OFFICIAL,
) -> MessageInputContext:
    actor = ActorRef(
        platform,
        "1001" if platform is Platform.ONEBOT else "member-openid",
        "member",
        "group-openid",
        "official-app",
    )
    conversation = ConversationRef(
        platform,
        "group",
        "group-openid",
        "official-app",
    )
    return MessageInputContext(
        IncomingMessageRef(
            platform,
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
    IdentityPrincipalService,
    PortableQuerySessions,
    ActorRef,
]:
    onebot = ActorRef(Platform.ONEBOT, "1001")
    service = Mock()
    pet = Mock()
    principals = IdentityPrincipalService()
    if linked:
        principals.register_official_link(
            onebot_qq_id=onebot.id,
            official=OfficialIdentity(
                "official-app",
                "member",
                "member-openid",
            ),
        )
    return service, pet, principals, PortableQuerySessions(), onebot


def _operations(
    service: Mock,
    pet: Mock,
    identity: IdentityPrincipalService,
    sessions: PortableQuerySessions,
    *,
    bound_player_id: int | None = 90002,
) -> dict[str, _Operation]:
    return cast(
        "dict[str, _Operation]",
        build_portable_lucky_skin_operations(
            cast("LuckySkinWindowService", service),
            cast("PetQueryService", pet),
            FeatureService(
                {
                    _context(platform=platform).message.conversation: frozenset(
                        {"seer_pet"}
                    )
                    for platform in (Platform.ONEBOT, Platform.QQ_OFFICIAL)
                },
                {},
                frozenset(),
                principals=identity,
            ),
            sessions,
            PlayerIdResolver(
                lambda value, _conversation: (
                    int(value) if value.isdecimal() else {"示例账号": 90002}.get(value)
                ),
                lambda _actor: bound_player_id,
            ),
            identity,
        ),
    )


@pytest.mark.asyncio
async def test_unlinked_official_identity_uses_its_player_binding_for_query() -> None:
    service, pet, identity, sessions, _ = _dependencies(linked=False)
    service.cached_query.side_effect = LuckySkinWindowAccessError(
        "该账号今日尚未缓存，只有 TOML 授权用户可以登录查询。"
    )
    operations = _operations(service, pet, identity, sessions)
    context = _context()

    reply = await operations["seer.lucky_skin_window.query"]("橱窗", context)

    assert "只有 TOML 授权用户可以登录查询" in _text(reply)
    assert sessions.active_prompt(context) is None
    service.cached_query.assert_called_once_with(
        LuckySkinQuery(context.message.actor, None, 90002)
    )


@pytest.mark.asyncio
async def test_unlinked_unbound_official_identity_still_requires_link() -> None:
    service, pet, identity, sessions, _ = _dependencies(linked=False)
    operations = _operations(
        service,
        pet,
        identity,
        sessions,
        bound_player_id=None,
    )

    reply = await operations["seer.lucky_skin_window.query"]("橱窗", _context())

    assert "关联官方账号" in _text(reply)
    service.cached_query.assert_not_called()


@pytest.mark.asyncio
async def test_configured_official_identity_uses_canonical_onebot_account() -> None:
    service, pet, principals, sessions, onebot = _dependencies()
    features = FeatureService({}, {}, frozenset(), principals=principals)
    result = LuckySkinWindowResult("2026-09-15", 90001, (), from_cache=True)
    service.cached_query.return_value = result
    service.detail_choices.return_value = ()
    service.result_message = AsyncMock(
        return_value=OutboundMessage.from_text("【幸运橱窗】")
    )
    operations = build_portable_lucky_skin_operations(
        cast("LuckySkinWindowService", service),
        cast("PetQueryService", pet),
        features,
        sessions,
        PlayerIdResolver(lambda *_: None, lambda _actor: 90002),
        principals,
    )
    context = _context()

    reply = await operations["seer.lucky_skin_window.query"]("橱窗", context)

    service.cached_query.assert_called_once_with(
        LuckySkinQuery(context.message.actor, onebot)
    )
    assert isinstance(reply, OutboundMessage)
    assert _text(reply) == "【幸运橱窗】"


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_cached_query_uses_linked_account_and_skin_buttons(
    platform: Platform,
) -> None:
    service, pet, identity, sessions, onebot = _dependencies()
    result = LuckySkinWindowResult("2026-09-15", 90001, (), from_cache=True)
    choice = QueryChoice(
        "测试皮肤",
        "101 / 1400101",
        PetImageSelection(1400101, "测试皮肤", skin_id=101),
    )
    service.cached_query.return_value = result
    service.detail_choices.return_value = (choice,)
    service.result_message = AsyncMock(
        return_value=OutboundMessage.from_text("【幸运橱窗】")
    )
    pet.select_image = AsyncMock(
        return_value=QueryResult(reply=QueryReply(text="皮肤详情"))
    )
    operations = _operations(service, pet, identity, sessions)
    context = _context(platform=platform)

    menu = await operations["seer.lucky_skin_window.query"]("橱窗", context)
    selected = await sessions.select("1", context)

    service.cached_query.assert_called_once_with(
        LuckySkinQuery(context.message.actor, onebot),
    )
    assert menu.prompt is not None
    assert menu.prompt.choices[0].label == "测试皮肤"
    assert selected is not None
    assert _text(selected) == "皮肤详情"


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_uncached_query_runs_only_after_confirmation(platform: Platform) -> None:
    service, pet, identity, sessions, onebot = _dependencies()
    result = LuckySkinWindowResult("2026-09-15", 90001, (), from_cache=False)
    service.cached_query.return_value = None
    service.query = AsyncMock(return_value=result)
    service.detail_choices.return_value = ()
    service.result_message = AsyncMock(
        return_value=OutboundMessage.from_text("【幸运橱窗】")
    )
    operations = _operations(service, pet, identity, sessions)
    context = _context(platform=platform)

    confirmation = await operations["seer.lucky_skin_window.query"]("橱窗", context)
    service.query.assert_not_awaited()
    result_message = await sessions.select("1", context)

    assert confirmation.prompt is not None
    assert tuple(choice.label for choice in confirmation.prompt.choices) == (
        "确认查询",
        "取消查询",
        "退出",
    )
    service.query.assert_awaited_once_with(
        LuckySkinQuery(context.message.actor, onebot),
    )
    assert result_message is not None
    assert _text(result_message) == "【幸运橱窗】"


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_cancelled_query_never_logs_in(platform: Platform) -> None:
    service, pet, identity, sessions, _ = _dependencies()
    service.cached_query.return_value = None
    service.query = AsyncMock()
    context = _context(platform=platform)
    await _operations(service, pet, identity, sessions)["seer.lucky_skin_window.query"](
        context.text, context
    )
    cancelled = await sessions.select("2", context)
    assert cancelled is not None
    assert "已取消" in _text(cancelled)
    service.query.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", ["90002", "示例账号", ""])
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_target_query_preserves_account_through_confirmation(
    reference: str,
    platform: Platform,
) -> None:
    service, pet, identity, sessions, onebot = _dependencies()
    context = _context(f"橱窗{reference}", platform=platform)
    if not reference:
        context = replace(
            context,
            message=replace(
                context.message,
                direct_mentions=(replace(context.message.actor, id="member-target"),),
            ),
        )
    result = LuckySkinWindowResult("2026-09-15", 90002, (), from_cache=False)
    service.cached_query.return_value = None
    service.query = AsyncMock(return_value=result)
    service.detail_choices.return_value = ()
    service.result_message = AsyncMock(return_value=OutboundMessage.from_text("result"))
    await _operations(service, pet, identity, sessions)["seer.lucky_skin_window.query"](
        context.text, context
    )
    expected = LuckySkinQuery(context.message.actor, onebot, 90002)
    service.cached_query.assert_called_once_with(expected)
    service.query.assert_not_awaited()
    await sessions.select("1", context)
    service.query.assert_awaited_once_with(expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("selection", ["2", "0"])
async def test_partial_account_menu_precedes_lucky_window_login_confirmation(
    platform: Platform,
    selection: str,
) -> None:
    service, pet, identity, sessions, onebot = _dependencies()
    service.cached_query.return_value = None
    service.query = AsyncMock(
        return_value=LuckySkinWindowResult("2026-09-15", 90002, (), from_cache=False),
    )
    service.detail_choices.return_value = ()
    service.result_message = AsyncMock(return_value=OutboundMessage.from_text("result"))
    resolver = PlayerIdResolver(
        lambda _reference, _conversation: None,
        lambda _actor: None,
        reference_search=lambda _reference, _actor, _conversation: (
            PlayerReferenceChoice(90001, "示例甲"),
            PlayerReferenceChoice(90002, "示例乙"),
        ),
    )
    operations = build_portable_lucky_skin_operations(
        cast("LuckySkinWindowService", service),
        cast("PetQueryService", pet),
        FeatureService({}, {}, frozenset(), principals=identity),
        sessions,
        resolver,
        identity,
    )
    context = _context("橱窗示例", platform=platform)
    menu = await operations["seer.lucky_skin_window.query"](context.text, context)
    assert isinstance(menu, OutboundMessage)
    assert "示例甲" in _text(menu) and "示例乙" in _text(menu)
    service.cached_query.assert_not_called()
    service.query.assert_not_awaited()
    await sessions.select(selection, context)
    if selection == "0":
        service.cached_query.assert_not_called()
        assert sessions.active_prompt(context) is None
    else:
        expected = LuckySkinQuery(context.message.actor, onebot, 90002)
        service.cached_query.assert_called_once_with(expected)
        service.query.assert_not_awaited()
        await sessions.select("1", context)
        service.query.assert_awaited_once_with(expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_watch_operations_reuse_linked_onebot_preferences(
    platform: Platform,
) -> None:
    service, pet, identity, sessions, onebot = _dependencies()
    item = LuckySkinWatchItem(101, 1400101, "测试皮肤")
    service.watch_list_message.return_value = "关注列表"
    service.resolve_watch_candidates.return_value = (item,)
    service.watch_change_message.side_effect = lambda _actor, selected, *, watched: (
        f"{'已关注' if watched else '已取消关注'}：{selected.name}"
    )
    service.watch_clear_message.return_value = "已清空关注皮肤。"
    service.watch_reset_message.return_value = "已恢复 TOML 初始关注列表。"
    operations = _operations(service, pet, identity, sessions)

    replies = (
        await operations["seer.lucky_skin_window.watch.list"](
            "关注橱窗", _context("关注橱窗", platform=platform)
        ),
        await operations["seer.lucky_skin_window.watch.add"](
            "关注橱窗测试", _context("关注橱窗测试", platform=platform)
        ),
        await operations["seer.lucky_skin_window.watch.remove"](
            "取消关注橱窗测试", _context("取消关注橱窗测试", platform=platform)
        ),
        await operations["seer.lucky_skin_window.watch.clear"](
            "清空关注橱窗", _context("清空关注橱窗", platform=platform)
        ),
        await operations["seer.lucky_skin_window.watch.reset"](
            "重置关注橱窗", _context("重置关注橱窗", platform=platform)
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
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_ambiguous_watch_change_uses_named_selection_buttons(
    platform: Platform,
) -> None:
    service, pet, identity, sessions, onebot = _dependencies()
    candidates = (
        LuckySkinWatchItem(101, 1400101, "皮肤甲"),
        LuckySkinWatchItem(102, 1400102, "皮肤乙"),
    )
    service.resolve_watch_candidates.return_value = candidates
    service.watch_change_message.return_value = "已关注：皮肤乙"
    operations = _operations(service, pet, identity, sessions)
    context = _context("关注橱窗皮肤", platform=platform)

    menu = await operations["seer.lucky_skin_window.watch.add"]("关注橱窗皮肤", context)
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "text"),
    [
        ("list", "关注橱窗"),
        ("add", "关注橱窗测试"),
        ("remove", "取消关注橱窗测试"),
        ("clear", "清空关注橱窗"),
        ("reset", "重置关注橱窗"),
    ],
)
async def test_unlinked_identity_cannot_read_or_change_watch_preferences(
    action: str,
    text: str,
) -> None:
    service, pet, identity, sessions, _ = _dependencies(linked=False)
    reply = await _operations(service, pet, identity, sessions)[
        f"seer.lucky_skin_window.watch.{action}"
    ](text, _context(text))
    assert "关联官方账号" in _text(reply)
    assert service.mock_calls == []
