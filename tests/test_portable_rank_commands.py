from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.core.command_catalog import CommandContext
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.portable_rank_commands import (
    build_portable_rank_admin_operations,
    build_portable_rank_operations,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.rank_command_contracts import rank_help_command_contracts

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.services.portable_reply import PortableReply
    from ironsbot.services.seer.rank_admin import RankAdminService
    from ironsbot.services.seer.rank_list_models import (
        RankCacheBatchCommand,
        RankListCommand,
        RankPageCacheRefreshCommand,
        RankPageCacheStatusCommand,
        RankPlayerCommand,
        RankScoreCommand,
    )
    from ironsbot.services.seer.rank_queries import RankQueryService


class _RankAdminService:
    def __init__(self, *, empty: bool = False) -> None:
        self.refresh_events: list[str] = []
        self.empty = empty

    def cache_status(self, conversation: ConversationRef | None) -> str:
        assert conversation is not None
        return f"samples:{conversation.id}"

    def page_overview(self) -> str:
        return "page overview"

    def page_status(self, command: RankPageCacheStatusCommand) -> str:
        return f"page:{command.rank_key}"

    async def cache_refresh(self, *, actor: ActorRef, progress: object) -> str:
        self.refresh_events.append(f"prepare:{actor.id}")
        if self.empty:
            return "empty"
        await cast("Callable[[str], Awaitable[None]]", progress)("refreshing")
        self.refresh_events.append("execute")
        return "refreshed"

    async def page_refresh(
        self,
        command: RankPageCacheRefreshCommand,
        *,
        actor: ActorRef,
        progress: object,
    ) -> str:
        self.refresh_events.append(f"page-prepare:{actor.id}:{command.rank_key}")
        await cast("Callable[[str], Awaitable[None]]", progress)("page refreshing")
        self.refresh_events.append("page-execute")
        return "page refreshed"

    async def cache_batch(
        self,
        command: RankCacheBatchCommand,
        *,
        actor: ActorRef,
        progress: object,
    ) -> str:
        self.refresh_events.append(
            f"batch-prepare:{actor.id}:{command.rank_key}:"
            f"{command.start_rank}-{command.end_rank}"
        )
        await cast("Callable[[str], Awaitable[None]]", progress)("batch caching")
        self.refresh_events.append("batch-execute")
        return "batch cached"


class _RankQueryService:
    def __init__(self) -> None:
        self.delivered: list[tuple[str, int]] = []
        self.display_permissions: list[bool] = []

    def default_limit(self, _conversation: ConversationRef | None) -> int:
        return 17

    def set_display_limit(
        self,
        *,
        conversation: ConversationRef | None,
        actor: ActorRef,
        can_manage: bool,
        limit: int,
    ) -> str:
        assert conversation is not None
        self.display_permissions.append(can_manage)
        return f"display:{conversation.account_id}:{conversation.id}:{actor.id}:{limit}"

    async def list(
        self,
        command: RankListCommand,
        *,
        actor: ActorRef | None = None,
        conversation: ConversationRef | None = None,
    ) -> str:
        del actor, conversation
        return (
            f"list:{command.kind}:{command.rank_key}:"
            f"{command.start_rank}:{command.limit}"
        )

    async def score(
        self,
        command: RankScoreCommand,
        *,
        conversation: ConversationRef | None,
        actor: ActorRef | None = None,
    ) -> str:
        del actor, conversation
        return f"score:{command.rank_key}:{command.score}"

    async def player(
        self,
        command: RankPlayerCommand,
        *,
        actor: ActorRef | None = None,
        conversation: ConversationRef | None = None,
    ) -> str:
        del actor, conversation
        return f"player:{command.rank_key}:{command.player_id}"

    async def prepare_player(
        self,
        command: RankPlayerCommand,
        *,
        actor: ActorRef | None = None,
        conversation: ConversationRef | None = None,
    ) -> _PreparedRankReply:
        del actor, conversation
        return _PreparedRankReply(
            f"player:{command.rank_key}:{command.player_id}",
            self.delivered,
            (command.rank_key, command.player_id),
        )


@dataclass(frozen=True, slots=True)
class _PreparedRankReply:
    message: str
    deliveries: list[tuple[str, int]]
    delivery: tuple[str, int]

    def delivered(self) -> None:
        self.deliveries.append(self.delivery)


def _resolver(*, target_binding: int | None = 800001) -> PlayerIdResolver:
    def lookup(
        reference: str,
        _conversation: ConversationRef,
    ) -> int | None:
        if reference.isdecimal():
            return int(reference)
        return {"别名": 700001}.get(reference)

    return PlayerIdResolver(
        lookup,
        lambda actor: (
            target_binding if actor.id == "target-openid" else 600001
        ),
    )


def _context(
    text: str,
    *,
    mentions: tuple[ActorRef, ...] = (),
    group_role: str | None = None,
) -> MessageInputContext:
    conversation = ConversationRef(Platform.QQ_OFFICIAL, "group", "group-openid")
    actor = ActorRef(
        Platform.QQ_OFFICIAL,
        "caller-openid",
        "member",
        conversation.id,
    )
    return MessageInputContext(
        IncomingMessageRef(
            platform=Platform.QQ_OFFICIAL,
            actor=actor,
            conversation=conversation,
            message_id=f"message-{text}",
            text=text,
            direct_mentions=mentions,
            group_role=group_role,
        ),
        mentions_bot=True,
    )


def _target() -> ActorRef:
    return ActorRef(
        Platform.QQ_OFFICIAL,
        "target-openid",
        "member",
        "group-openid",
    )


def _text(message: OutboundMessage) -> str:
    part = message.parts[0]
    assert isinstance(part, TextPart)
    return part.text


@pytest.mark.asyncio
async def test_portable_rank_dispatches_list_score_and_alias_player_queries() -> None:
    service = _RankQueryService()
    operations = build_portable_rank_operations(
        cast("RankQueryService", service),
        _resolver(),
        FeatureService({}, {}, frozenset()),
    )
    operation = operations["rank.global_collection"]

    listed = cast(
        "OutboundMessage",
        await operation("成就榜", _context("成就榜")),
    )
    scored = cast(
        "OutboundMessage",
        await operation("成就榜5000点", _context("成就榜5000点")),
    )
    player = cast(
        "PortableReply",
        await operation("成就榜别名", _context("成就榜别名")),
    )

    assert _text(listed) == "list:global:成就点数:1:17"
    assert _text(scored) == "score:成就点数:5000"
    assert _text(player.message) == "player:成就点数:700001"
    assert service.delivered == []
    player.delivered()
    assert service.delivered == [("成就点数", 700001)]


@pytest.mark.asyncio
async def test_portable_rank_display_limit_uses_full_platform_identity() -> None:
    service = _RankQueryService()
    operations = build_portable_rank_operations(
        cast("RankQueryService", service),
        _resolver(),
        FeatureService({}, {}, frozenset()),
    )
    context = _context("/榜单显示 20", group_role="owner")

    result = cast(
        "OutboundMessage",
        await operations["rank.display_limit"]("榜单显示 20", context),
    )

    assert _text(result) == "display:None:group-openid:caller-openid:20"
    assert service.display_permissions == [True]


@pytest.mark.asyncio
async def test_portable_rank_display_limit_rechecks_group_management() -> None:
    service = _RankQueryService()
    operations = build_portable_rank_operations(
        cast("RankQueryService", service),
        _resolver(),
        FeatureService({}, {}, frozenset()),
    )
    context = _context("/榜单显示 20")

    await operations["rank.display_limit"]("榜单显示 20", context)

    assert service.display_permissions == [False]


@pytest.mark.asyncio
async def test_rank_with_direct_mention_uses_member_openid_binding() -> None:
    operations = build_portable_rank_operations(
        cast("RankQueryService", _RankQueryService()),
        _resolver(),
        FeatureService({}, {}, frozenset()),
    )
    context = _context("成就榜", mentions=(_target(),))

    result = cast(
        "PortableReply",
        await operations["rank.global_collection"](context.text, context),
    )

    assert _text(result.message) == "player:成就点数:800001"


def test_rank_catalog_claims_a_direct_member_mention_as_player_query() -> None:
    resolver = _resolver()
    contract = next(
        item
        for item in rank_help_command_contracts(resolver)
        if item.id == "rank.global_collection"
    )
    context = _context("成就榜", mentions=(_target(),))

    assert contract.matches_direct_input(
        CommandContext(
            actor=context.message.actor,
            conversation=context.message.conversation,
            member_mentions=context.member_mentions,
        ),
        context.text,
    )


@pytest.mark.asyncio
async def test_rank_reports_an_unbound_mentioned_openid() -> None:
    operations = build_portable_rank_operations(
        cast("RankQueryService", _RankQueryService()),
        _resolver(target_binding=None),
        FeatureService({}, {}, frozenset()),
    )
    context = _context("成就榜", mentions=(_target(),))

    result = cast(
        "PortableReply",
        await operations["rank.global_collection"](context.text, context),
    )

    assert _text(result.message) == "该成员尚未绑定米米号。"


@pytest.mark.asyncio
async def test_rank_rejects_mixed_alias_and_member_mention() -> None:
    operations = build_portable_rank_operations(
        cast("RankQueryService", _RankQueryService()),
        _resolver(),
        FeatureService({}, {}, frozenset()),
    )
    context = _context("成就榜别名", mentions=(_target(),))

    result = cast(
        "PortableReply",
        await operations["rank.global_collection"](context.text, context),
    )

    assert _text(result.message) == (
        "米米号或玩家别名和 @成员 不能同时使用，请保留其中一种。"
    )


@pytest.mark.asyncio
async def test_portable_rank_admin_operations_include_deferred_refresh() -> None:
    service = _RankAdminService()
    operations = build_portable_rank_admin_operations(
        cast("RankAdminService", service)
    )
    context = _context("/榜单情况")

    samples = await operations["rank.sample_status"]("样本情况", context)
    overview = await operations["rank.page_status"]("榜单情况", context)
    detail = await operations["rank.page_status"]("榜单情况 图鉴榜", context)
    refresh = cast(
        "PortableReply",
        await operations["rank.sample_refresh"]("刷新样本", context),
    )

    assert isinstance(samples, OutboundMessage)
    assert isinstance(overview, OutboundMessage)
    assert isinstance(detail, OutboundMessage)
    assert _text(samples) == "samples:group-openid"
    assert _text(overview) == "page overview"
    assert _text(detail) == "page:图鉴积分"
    assert _text(refresh.message) == "refreshing"
    assert service.refresh_events == ["prepare:caller-openid"]

    refresh.delivered()
    assert refresh.follow_up is not None
    final = await refresh.follow_up()

    assert isinstance(final, OutboundMessage)
    assert _text(final) == "refreshed"
    assert service.refresh_events == ["prepare:caller-openid", "execute"]


@pytest.mark.asyncio
async def test_portable_rank_refresh_without_progress_stays_single_reply() -> None:
    operations = build_portable_rank_admin_operations(
        cast("RankAdminService", _RankAdminService(empty=True))
    )

    refresh = cast(
        "PortableReply",
        await operations["rank.sample_refresh"]("刷新样本", _context("刷新样本")),
    )

    assert _text(refresh.message) == "empty"
    assert refresh.follow_up is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "command_id",
        "text",
        "progress_text",
        "events",
        "final_text",
    ),
    [
        (
            "rank.page_refresh",
            "/刷新榜单 图鉴榜",
            "page refreshing",
            ("page-prepare:caller-openid:图鉴积分", "page-execute"),
            "page refreshed",
        ),
        (
            "rank.page_batch",
            "/缓存榜单 刻印榜 1-100",
            "batch caching",
            ("batch-prepare:caller-openid:刻印图鉴:1-100", "batch-execute"),
            "batch cached",
        ),
    ],
)
async def test_portable_rank_page_maintenance_uses_deferred_reply(
    command_id: str,
    text: str,
    progress_text: str,
    events: tuple[str, str],
    final_text: str,
) -> None:
    service = _RankAdminService()
    operation = build_portable_rank_admin_operations(
        cast("RankAdminService", service)
    )[command_id]

    reply = cast("PortableReply", await operation(text, _context(text)))

    assert _text(reply.message) == progress_text
    assert service.refresh_events == [events[0]]

    reply.delivered()
    assert reply.follow_up is not None
    final = await reply.follow_up()

    assert isinstance(final, OutboundMessage)
    assert _text(final) == final_text
    assert service.refresh_events == list(events)
