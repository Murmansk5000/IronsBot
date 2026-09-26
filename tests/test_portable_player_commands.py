from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.config.models.seer import PlayerBindingConfig
from ironsbot.core.command_catalog import command_context_from_input
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, SendResult, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.player_references import PlayerReferenceChoice
from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.services.operations.request_feedback import send_request_feedback
from ironsbot.services.portable_player_commands import (
    build_portable_player_operations as _build_player_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.portable_reply import PortableReply
from ironsbot.services.seer.command_contracts import seer_command_contracts
from ironsbot.services.seer.player_binding import PlayerBindingState
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailActionRequest,
    PlayerDetailExtensionAction,
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.player_query import PlayerQuerySectionPlan
from ironsbot.services.seer.player_service_models import (
    PendingPlayerQuery,
    PlayerBaseSnapshot,
    PlayerQueryResult,
)
from ironsbot.services.seer.query_result import QueryReply
from ironsbot.services.seer.rank_models import RankLookupResult
from ironsbot.services.seer.rank_queries import RankPlayerPreparedReply

if TYPE_CHECKING:
    from ironsbot.services.portable_reply import PortableOperation
    from ironsbot.services.seer.player_service import PlayerService
    from ironsbot.services.seer.player_shortcut_contracts import (
        PlayerShortcutCommand,
    )
    from ironsbot.services.seer.rank_queries import RankQueryService


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_beast_rank_choice_is_lazy_and_shared_query_uses_responder(
    platform: Platform,
) -> None:
    player_id = 700001
    owner = _context(f"米米号{player_id}", platform=platform)
    features = FeatureService(
        {owner.message.conversation: frozenset({"seer_player", "seer_rank"})},
        {},
        frozenset(),
    )
    charged: list[str] = []
    rank = SimpleNamespace(
        prepare_player=AsyncMock(
            return_value=RankPlayerPreparedReply(
                "玄武榜玩家结果",
                on_delivered=lambda: charged.append("responder"),
                lookup=RankLookupResult(
                    title="北冥试炼·玄武",
                    score_name="完成时间",
                    rank=224,
                    score=1_790_272_228,
                ),
            )
        )
    )
    sessions = PortableQuerySessions()
    operations = _build_player_operations(
        cast("PlayerService", _PlayerService()),
        _resolver(),
        sessions,
        features,
        PlayerDetailExtensionRegistry(),
        cast("RankQueryService", rank),
    )
    initial = cast(
        "PortableReply",
        await operations["seer.player.query"](owner.text, owner),
    )
    assert "4. 【神兽榜】" in _text(initial)
    initial.delivered()
    rank.prepare_player.assert_not_awaited()
    sessions.record_delivery(
        owner, initial.message, SendResult(delivered=True, message_id="player-menu")
    )
    responder = _context(
        "4", platform=platform, actor_id="another-member", reply_to_id="player-menu"
    )
    selected = await sessions.select_shared("4", owner, responder, allow_deferred=True)
    assert isinstance(selected, PortableReply)
    expected = "【神兽榜】\n\n玄武榜玩家结果"
    assert _text(selected) == expected
    assert rank.prepare_player.await_args.kwargs["actor"] == responder.message.actor
    assert rank.prepare_player.await_args.args[0].player_id == player_id
    assert sessions.has_active_session(owner)
    assert not sessions.has_active_session(responder)
    assert charged == []
    selected.delivered()
    assert charged == ["responder"]
    direct = await sessions.select("4", owner, allow_deferred=True)
    assert isinstance(direct, PortableReply)
    assert _text(direct) == expected
    assert rank.prepare_player.await_args.kwargs["actor"] == owner.message.actor
    assert sessions.has_active_session(owner)


@pytest.mark.asyncio
async def test_shared_player_menu_cannot_launder_numeric_superuser_target() -> None:
    player_id = 700001
    owner = _context(f"米米号{player_id}", actor_id="owner")
    features = FeatureService(
        {owner.message.conversation: frozenset({"seer_player"})},
        {},
        frozenset(),
    )
    resolver = PlayerIdResolver(
        lambda reference, _conversation: (
            int(reference) if reference.isdecimal() else None
        ),
        lambda actor: player_id if actor.id == "owner" else 600001,
        binding_config=PlayerBindingConfig(),
        superuser_actors=lambda: (owner.message.actor,),
    )
    service = _PlayerService()
    sessions = PortableQuerySessions()
    operations = _build_player_operations(
        cast("PlayerService", service),
        resolver,
        sessions,
        features,
        PlayerDetailExtensionRegistry(),
    )
    initial = await operations["seer.player.query"](owner.text, owner)
    assert isinstance(initial, PortableReply)
    sessions.record_delivery(
        owner, initial.message, SendResult(delivered=True, message_id="owner-menu")
    )
    responder = _context("1", actor_id="responder", reply_to_id="owner-menu")
    selected = await sessions.select_shared("1", owner, responder, allow_deferred=True)
    assert isinstance(selected, OutboundMessage)
    assert isinstance(selected.parts[0], TextPart)
    assert "完整数字" in selected.parts[0].text


@pytest.mark.asyncio
async def test_beast_rank_menu_requires_rank_permission() -> None:
    owner = _context("米米号700001")
    features = FeatureService(
        {owner.message.conversation: frozenset({"seer_player"})},
        {},
        frozenset(),
    )
    rank = SimpleNamespace(prepare_player=AsyncMock())
    operations = _build_player_operations(
        cast("PlayerService", _PlayerService()),
        _resolver(),
        PortableQuerySessions(),
        features,
        PlayerDetailExtensionRegistry(),
        cast("RankQueryService", rank),
    )
    initial = cast(
        "PortableReply",
        await operations["seer.player.query"](owner.text, owner),
    )
    assert "神兽榜" not in _text(initial)
    rank.prepare_player.assert_not_awaited()


@pytest.mark.asyncio
async def test_bare_beast_rank_uses_own_binding_even_with_another_player_menu() -> None:
    owner = _context("米米号700001")
    own_player_id = 600001
    features = FeatureService(
        {owner.message.conversation: frozenset({"seer_player", "seer_rank"})},
        {},
        frozenset(),
    )
    rank = SimpleNamespace(
        prepare_player=AsyncMock(
            return_value=RankPlayerPreparedReply("rank result", lookup=None)
        )
    )
    sessions = PortableQuerySessions()
    operations = _build_player_operations(
        cast("PlayerService", _PlayerService()),
        _resolver(),
        sessions,
        features,
        PlayerDetailExtensionRegistry(),
        cast("RankQueryService", rank),
    )
    opened = cast(
        "PortableReply", await operations["seer.player.query"](owner.text, owner)
    )
    opened.delivered()
    selected = await sessions.select("神兽榜", _context("神兽榜"), allow_deferred=True)
    assert isinstance(selected, PortableReply)
    assert rank.prepare_player.await_args.args[0].player_id == own_player_id


class _PlayerService:
    def shortcut_binding_offer(self, player_id: int) -> str:
        return f"是否绑定 {player_id}？"

    def bind_shortcut_target(self, actor: ActorRef, player_id: int) -> str:
        self.bound.append((actor, player_id))
        self.unbound = False
        return "已绑定"

    def default_player_id(self, actor: ActorRef) -> int | None:
        del actor
        return None if self.unbound else 600001

    def should_offer_binding(self, actor: ActorRef) -> bool:
        return self.default_player_id(actor) is None and not self.choice_completed

    def decline_binding_offer(self, actor: ActorRef) -> None:
        del actor
        self.choice_completed = True

    def __init__(self, *, replacement: bool = False, team_id: int = 0) -> None:
        self.queried: list[int] = []
        self.returned: list[tuple[ActorRef, int]] = []
        self.refreshed: list[int] = []
        self.bound: list[tuple[ActorRef, int]] = []
        self.replacement = replacement
        self.team_id = team_id
        self.unbound = False
        self.choice_completed = False
        self.replacement_choices: list[tuple[ActorRef, int]] = []

    async def query(
        self,
        player_id: int,
        *,
        actor: ActorRef,
        explicit: bool,
        conversation: ConversationRef | None,
    ) -> PlayerQueryResult:
        del actor, conversation
        self.queried.append(player_id)
        return PlayerQueryResult(
            pending=_pending(player_id, team_id=self.team_id),
            offer_binding=explicit and self.unbound,
        )

    async def bind_player(
        self,
        player_id: int,
        *,
        actor: ActorRef,
        conversation: ConversationRef | None,
        target: ActorRef | None = None,
    ) -> PlayerQueryResult:
        del conversation
        self.bound.append((target or actor, player_id))
        return PlayerQueryResult(
            pending=_pending(player_id),
            offer_binding=self.replacement,
            binding_replacement=(
                PlayerBindingState(
                    actor=actor,
                    player_id=600001,
                    player_nick="old",
                    choice_completed=True,
                    last_changed_at=None,
                )
                if self.replacement
                else None
            ),
        )

    def save_binding_choice(
        self,
        actor: ActorRef,
        pending: PendingPlayerQuery,
        *,
        accepted: bool,
        replacing_existing: bool = False,
    ) -> str:
        if not replacing_existing:
            if accepted:
                self.bound.append((actor, pending.player_id))
            pending.player_message = f"choice:{accepted}\n{pending.player_message}"
            return "choice saved"
        if accepted:
            self.replacement_choices.append((actor, pending.player_id))
        pending.player_message = (
            f"{'replaced' if accepted else 'retained'}:{pending.player_id}\n"
            f"{pending.player_message}"
        )
        return "replaced"

    def binding_offer(
        self,
        pending: PendingPlayerQuery,
        *,
        replacement: PlayerBindingState | None = None,
    ) -> str:
        if replacement is not None:
            return (
                f"当前默认米米号：{replacement.player_id}\n"
                f"已查到米米号：{pending.player_id}（tester）\n\n"
                "是否将默认米米号改为该账号？\n"
                "回复“是”或“y”确认，回复“否”或“n”保留当前绑定。"
            )
        return (
            f"已查到米米号：{pending.player_id}（tester）\n\n"
            "是否将其设为默认米米号？\n"
            "回复“是”或“y”确认，回复“否”或“n”跳过。"
        )

    async def shortcut(
        self,
        command: PlayerShortcutCommand,
        actor: ActorRef,
        *,
        conversation: ConversationRef | None,
    ) -> QueryReply:
        del conversation
        return QueryReply(text=f"{actor.id}:{command.kind}:{command.player_id}")

    def unbind(self, actor: ActorRef) -> str:
        return f"unbound:{actor.id}"

    def record_returned_query(
        self,
        actor: ActorRef,
        pending: PendingPlayerQuery,
    ) -> None:
        self.returned.append((actor, pending.player_id))

    def start_background_refresh(
        self,
        pending: PendingPlayerQuery,
        *,
        conversation: ConversationRef | None,
    ) -> None:
        del conversation
        self.refreshed.append(pending.player_id)


def _pending(player_id: int, *, team_id: int = 0) -> PendingPlayerQuery:
    user_info = SimpleNamespace(nick="tester", team_id=team_id)
    more_info = SimpleNamespace()
    return PendingPlayerQuery(
        player_id=player_id,
        user_info=user_info,
        more_info=more_info,
        player_message=f"player:{player_id}",
        section_plan=PlayerQuerySectionPlan(
            show_local_rank=False,
            has_collection=True,
            needs_peak_section=True,
            has_autocard_rank=True,
            needs_online_info=False,
            local_rank_enabled=False,
        ),
        base_snapshot=(
            PlayerBaseSnapshot(
                player_id,
                user_info,
                more_info,
                None,
                "星痕",
                None,
            )
            if team_id
            else None
        ),
    )


def _context(
    text: str,
    *,
    actor_id: str = "caller-openid",
    mentions: tuple[ActorRef, ...] = (),
    platform: Platform = Platform.QQ_OFFICIAL,
    reply_to_id: str | None = None,
) -> MessageInputContext:
    conversation = ConversationRef(platform, "group", "group-openid")
    actor = ActorRef(
        platform,
        actor_id,
        "member",
        conversation.id,
    )
    return MessageInputContext(
        IncomingMessageRef(
            platform=platform,
            actor=actor,
            conversation=conversation,
            message_id=f"message-{text}",
            text=text,
            direct_mentions=mentions,
            reply_to_id=reply_to_id,
        ),
        mentions_bot=True,
    )


def _resolver() -> PlayerIdResolver:
    def lookup(
        reference: str,
        _conversation: ConversationRef,
    ) -> int | None:
        if reference.isdecimal():
            return int(reference)
        return {"别名": 700001}.get(reference)

    return PlayerIdResolver(
        lookup,
        lambda actor: {
            "caller-openid": 600001,
            "target-openid": 800001,
        }.get(actor.id),
    )


def build_portable_player_operations(
    service: PlayerService,
    resolver: PlayerIdResolver,
    sessions: PortableQuerySessions,
    features: FeatureService | None = None,
    extensions: PlayerDetailExtensionRegistry | None = None,
) -> dict[str, PortableOperation]:
    return _build_player_operations(
        service,
        resolver,
        sessions,
        features
        or FeatureService(
            {
                _context("米米号", platform=platform).message.conversation: frozenset(
                    {"seer_player"}
                )
                for platform in (Platform.ONEBOT, Platform.QQ_OFFICIAL)
            },
            {},
            frozenset(),
        ),
        extensions or PlayerDetailExtensionRegistry(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("selection", ["1", "0"])
async def test_partial_binding_uses_shared_menu_before_business_work(
    platform: Platform,
    selection: str,
) -> None:
    service = _PlayerService()
    sessions = PortableQuerySessions()
    choices = (
        PlayerReferenceChoice(700001, "玩家甲"),
        PlayerReferenceChoice(700002, "玩家乙"),
    )
    resolver = PlayerIdResolver(
        lambda _reference, _conversation: None,
        lambda _actor: None,
        reference_search=lambda _reference, _actor, _conversation: choices,
    )
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        resolver,
        sessions,
    )
    context = _context("绑定米米号玩家", platform=platform)
    reply = cast(
        "PortableReply", await operations["seer.player.bind"](context.text, context)
    )
    assert "玩家甲" in _text(reply) and "玩家乙" in _text(reply)
    assert not service.bound
    stranger = _context(context.text, platform=platform, actor_id="stranger")
    assert await sessions.select("1", stranger, allow_deferred=True) is None
    selected = await sessions.select(selection, context, allow_deferred=True)
    assert selected is not None
    assert service.bound == (
        [(context.message.actor, 700001)] if selection == "1" else []
    )
    assert not service.returned
    if selection == "1":
        cast("PortableReply", selected).delivered()
        assert service.returned == [(context.message.actor, 700001)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prefix", "operation_id"),
    [
        ("绑定米米号", "seer.player.bind"),
        ("米米号", "seer.player.query"),
        ("收集", "seer.player.default"),
    ],
)
async def test_player_selection_rechecks_reference_visibility(
    prefix: str,
    operation_id: str,
) -> None:
    service = _PlayerService()
    sessions = PortableQuerySessions()
    choices = (
        PlayerReferenceChoice(700001, "玩家甲"),
        PlayerReferenceChoice(700002, "玩家乙"),
    )
    resolver = PlayerIdResolver(
        lambda _reference, _conversation: None,
        lambda _actor: None,
        reference_search=lambda _reference, _actor, _conversation: choices,
    )
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        resolver,
        sessions,
    )
    context = _context(f"{prefix}玩家")
    await operations[operation_id](context.text, context)
    choices = ()
    reply = await sessions.select("1", context, allow_deferred=True)
    assert isinstance(reply, OutboundMessage)
    assert "已不可用" in cast("TextPart", reply.parts[0]).text
    assert not service.bound
    assert not service.queried


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("prefix", ["米米号", "查询玩家信息", "收集", "巅峰", "群星牌"])
@pytest.mark.parametrize("selection", ["2", "button", "0"])
async def test_player_queries_use_declared_reference_selection(
    monkeypatch: pytest.MonkeyPatch,
    platform: Platform,
    prefix: str,
    selection: str,
) -> None:
    service = _PlayerService()
    query = AsyncMock(wraps=service.query)
    shortcut = AsyncMock(wraps=service.shortcut)
    monkeypatch.setattr(service, "query", query)
    monkeypatch.setattr(service, "shortcut", shortcut)
    sessions = PortableQuerySessions()
    resolver = PlayerIdResolver(
        lambda *_: None,
        lambda _: None,
        reference_search=lambda *_: (
            PlayerReferenceChoice(700001, "玩家甲"),
            PlayerReferenceChoice(700002, "玩家乙"),
        ),
    )
    context = _context(f"{prefix}玩家", platform=platform)
    operation_id = (
        "seer.player.query"
        if prefix in {"米米号", "查询玩家信息"}
        else "seer.player.default"
    )
    contract = next(
        item for item in seer_command_contracts(resolver) if item.id == operation_id
    )
    assert contract.routing_matcher is not None
    assert contract.routing_matcher(context.text, command_context_from_input(context))
    operation = build_portable_player_operations(
        cast("PlayerService", service),
        resolver,
        sessions,
    )[operation_id]
    reply = await operation(context.text, context)
    assert isinstance(reply, PortableReply)
    prompt = reply.message.prompt
    assert prompt is not None
    query.assert_not_awaited()
    shortcut.assert_not_awaited()
    if selection == "button":
        selection = prompt.action_data(prompt.choices[1])
    selected = await sessions.select(selection, context, allow_deferred=True)
    if selection == "0":
        query.assert_not_awaited()
        shortcut.assert_not_awaited()
        assert not sessions.has_active_session(context)
        return
    assert isinstance(selected, PortableReply)
    assert "700002" in _text(selected)
    if operation_id == "seer.player.query":
        query.assert_awaited_once_with(
            700002,
            actor=context.message.actor,
            explicit=True,
            conversation=context.message.conversation,
        )
        assert sessions.active_prompt(context) is not None
        assert not service.returned
        selected.delivered()
        assert service.returned == [(context.message.actor, 700002)]
    else:
        shortcut.assert_awaited_once()


def _text(reply: PortableReply) -> str:
    part = reply.message.parts[0]
    assert isinstance(part, TextPart)
    return part.text


@pytest.mark.asyncio
async def test_player_query_menu_commits_work_only_after_delivery() -> None:
    service = _PlayerService()
    sessions = PortableQuerySessions()
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        sessions,
    )
    context = _context("米米号700002")

    reply = cast(
        "PortableReply",
        await operations["seer.player.query"](context.text, context),
    )

    assert "player:700002" in _text(reply)
    assert "1. 【收集】" in _text(reply)
    assert "设为默认米米号" not in _text(reply)
    assert "绑定米米号700002" not in _text(reply)
    assert service.returned == []
    assert service.refreshed == []
    reply.delivered()
    assert service.returned == [(context.message.actor, 700002)]
    assert service.refreshed == [700002]

    selected = await sessions.select("1", context, allow_deferred=True)
    assert isinstance(selected, PortableReply)
    part = selected.message.parts[0]
    assert isinstance(part, TextPart)
    assert part.text == "caller-openid:collection:700002"


@pytest.mark.asyncio
async def test_player_query_menu_accepts_short_binding_confirmation() -> None:
    service = _PlayerService()
    service.unbound = True
    sessions = PortableQuerySessions()
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        sessions,
    )
    context = _context("米米号700002")

    await operations["seer.player.query"](context.text, context)
    selected = await sessions.select("y", context, allow_deferred=True)

    assert isinstance(selected, PortableReply)
    assert service.bound == [(context.message.actor, 700002)]
    part = selected.message.parts[0]
    assert isinstance(part, TextPart)
    assert "choice:True" in part.text


@pytest.mark.asyncio
async def test_unbound_shortcut_decline_is_not_offered_again() -> None:
    service = _PlayerService()
    service.unbound = True
    sessions = PortableQuerySessions()
    operations = build_portable_player_operations(
        cast("PlayerService", service), _resolver(), sessions
    )
    context = _context("收集700002")
    reply = await operations["seer.player.default"](context.text, context)
    assert isinstance(reply, PortableReply)
    assert "是否绑定" in _text(reply)
    reply.delivered()
    result = await sessions.select("n", context, allow_deferred=True)
    assert isinstance(result, PortableReply)
    assert "collection:700002" in _text(result)
    again = await operations["seer.player.default"](context.text, context)
    assert isinstance(again, PortableReply)
    assert "是否绑定" not in _text(again)
    assert "collection:700002" in _text(again)
    assert service.queried == []
    assert service.bound == []


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery_outcome", ["delivered", "failed"])
async def test_player_query_holds_fast_numeric_reply_until_prompt_delivery(
    delivery_outcome: str,
) -> None:
    service = _PlayerService()
    sessions = PortableQuerySessions()
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        sessions,
    )
    context = _context("米米号700002", platform=Platform.QQ_OFFICIAL)
    started = asyncio.Event()
    finish_query = asyncio.Event()
    original_query = service.query

    async def delayed_query(
        player_id: int,
        *,
        actor: ActorRef,
        explicit: bool,
        conversation: ConversationRef | None,
    ) -> PlayerQueryResult:
        started.set()
        await finish_query.wait()
        return await original_query(
            player_id,
            actor=actor,
            explicit=explicit,
            conversation=conversation,
        )

    service.query = AsyncMock(side_effect=delayed_query)
    query_task = asyncio.ensure_future(
        operations["seer.player.query"](context.text, context)
    )
    await started.wait()
    reply_context = replace(
        context,
        message=replace(
            context.message,
            message_id="fast-selection",
            text="1",
        ),
    )
    assert sessions.recognizes_response("1", reply_context)
    selection_task = asyncio.ensure_future(
        sessions.select("1", reply_context, allow_deferred=True)
    )
    await asyncio.sleep(0)
    assert not selection_task.done()

    finish_query.set()
    reply = cast("PortableReply", await query_task)
    await asyncio.sleep(0)
    assert not selection_task.done()

    if delivery_outcome == "delivered":
        reply.delivered()
        selected = await selection_task
        assert isinstance(selected, PortableReply)
        assert "collection:700002" in _text(selected)
        assert service.returned == [(context.message.actor, 700002)]
    else:
        reply.delivery_failed()
        assert await selection_task is None
        assert not sessions.has_active_session(context)
        assert service.returned == []


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("selection", ["y", "n", "button", "0"])
async def test_first_binding_confirmation_reuses_query_and_delivery(
    platform: Platform,
    selection: str,
) -> None:
    service = _PlayerService()
    service.unbound = True
    sessions = PortableQuerySessions()
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        sessions,
    )
    context = _context("米米号700002", platform=platform)
    reply = cast(
        "PortableReply",
        await operations["seer.player.query"](context.text, context),
    )
    assert not service.bound
    reply.delivered()
    prompt = reply.message.prompt
    assert prompt is not None
    action = prompt.action_data(prompt.choices[0])
    selected = await sessions.select(
        action if selection == "button" else selection,
        context,
        allow_deferred=True,
    )
    assert isinstance(selected, OutboundMessage if selection == "0" else PortableReply)
    assert service.bound == (
        [(context.message.actor, 700002)] if selection in {"y", "4", "button"} else []
    )
    assert service.queried == [700002]
    assert service.returned == []
    assert service.refreshed == []
    assert not sessions.recognizes_response("y", context)
    assert await sessions.select_action(action, context) is None
    if selection == "0":
        assert sessions.active_prompt(context) is None
    else:
        assert sessions.recognizes_response("收集", context)
        assert await sessions.select("收集", context, allow_deferred=True) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", ["4", "战队"])
@pytest.mark.parametrize("revoke", [False, True])
@pytest.mark.parametrize("manage", [False, True])
async def test_player_query_menu_includes_available_shared_extension(
    selection: str,
    *,
    revoke: bool,
    manage: bool,
) -> None:
    service = _PlayerService(team_id=9001)
    sessions = PortableQuerySessions()
    extensions = PlayerDetailExtensionRegistry()

    async def query(request: PlayerDetailActionRequest) -> QueryReply:
        assert request.can_manage is manage
        return QueryReply(text="team detail")

    extensions.register(
        PlayerDetailExtensionAction(
            id="player_team",
            feature="seer_team",
            label="战队",
            aliases=("战队",),
            command_help_id="seer.team.query",
            query=query,
            action=ActionDefinition("player_team", "玩家所属战队"),
        )
    )
    allowed = True
    features = cast(
        "Any",
        SimpleNamespace(
            is_feature_allowed=lambda *_args: allowed,
            is_actor_superuser=lambda _actor: False,
        ),
    )
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        sessions,
        features,
        extensions,
    )
    context = _context("米米号700002")
    context = replace(
        context,
        message=replace(
            context.message,
            group_role="member" if manage else "admin",
        ),
    )

    reply = cast(
        "PortableReply",
        await operations["seer.player.query"](context.text, context),
    )
    reply.delivered()

    assert "4. 【战队】星痕（战队ID：9001）" in _text(reply)
    allowed = not revoke
    selection_context = replace(
        context,
        message=replace(
            context.message,
            message_id="selection",
            group_role="admin" if manage else "member",
        ),
    )
    selected = await sessions.select(selection, selection_context, allow_deferred=True)
    assert isinstance(selected, OutboundMessage if revoke else PortableReply)
    part = (
        selected if isinstance(selected, OutboundMessage) else selected.message
    ).parts[0]
    assert isinstance(part, TextPart)
    assert part.text == ("当前会话没有使用该选项的权限。" if revoke else "team detail")


@pytest.mark.asyncio
@pytest.mark.parametrize("team_id", [0, 9001])
async def test_player_team_option_requires_membership_and_permission(
    team_id: int,
) -> None:
    context = _context("米米号700002")
    extensions = PlayerDetailExtensionRegistry()

    async def query(_request: PlayerDetailActionRequest) -> QueryReply:
        return QueryReply(text="team detail")

    extensions.register(
        PlayerDetailExtensionAction(
            id="player_team",
            feature="seer_team",
            label="战队",
            aliases=("战队",),
            command_help_id="seer.team.query",
            query=query,
            action=ActionDefinition("player_team", "玩家所属战队"),
        )
    )
    features = FeatureService(
        {context.message.conversation: frozenset({"seer_player"})},
        {},
        frozenset(),
    )
    operations = build_portable_player_operations(
        cast("PlayerService", _PlayerService(team_id=team_id)),
        _resolver(),
        PortableQuerySessions(),
        features,
        extensions,
    )
    reply = cast(
        "PortableReply",
        await operations["seer.player.query"](context.text, context),
    )
    assert "【战队】" not in _text(reply)


@pytest.mark.asyncio
async def test_quoted_player_menu_reauthorizes_replying_member() -> None:
    service = _PlayerService()
    sessions = PortableQuerySessions()
    allowed = True
    features = cast(
        "Any",
        SimpleNamespace(
            is_feature_allowed=lambda *_args: allowed,
            is_actor_superuser=lambda _actor: False,
        ),
    )
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        sessions,
        features,
    )
    owner = _context("米米号700002")
    initial = cast(
        "PortableReply",
        await operations["seer.player.query"](owner.text, owner),
    )
    initial.delivered()
    from ironsbot.core.outbound import SendResult

    sessions.record_delivery(
        owner, initial.message, SendResult(delivered=True, message_id="current-menu")
    )
    responder = _context(
        "1",
        actor_id="other-member",
        reply_to_id="current-menu",
    )
    allowed = False

    assert sessions.recognizes_shared_response("1", owner, responder)
    result = await sessions.select_shared("1", owner, responder, allow_deferred=True)

    assert isinstance(result, OutboundMessage)
    part = result.parts[0]
    assert isinstance(part, TextPart)
    assert part.text == "当前会话没有使用该选项的权限。"
    assert sessions.has_active_session(owner)
    assert not sessions.has_active_session(responder)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("inputs", [("收集", "巅峰", "群星牌"), ("1", "2", "3")])
async def test_player_detail_template_supports_repeated_named_and_numeric_choices(
    platform: Platform,
    inputs: tuple[str, str, str],
) -> None:
    service = _PlayerService()
    sessions = PortableQuerySessions()
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        sessions,
    )
    context = _context("米米号700002", platform=platform)
    initial = cast(
        "PortableReply",
        await operations["seer.player.query"](context.text, context),
    )
    initial.delivered()
    for text, kind in zip(inputs, ("collection", "peak", "autocard"), strict=True):
        assert sessions.recognizes_response(text, context)
        reply = await sessions.select(text, context, allow_deferred=True)
        assert isinstance(reply, PortableReply)
        assert f":{kind}:700002" in _text(reply)
        assert sessions.active_prompt(context) is not None
    assert not sessions.recognizes_response("随便聊天", context)
    await sessions.select("0", context)
    assert sessions.active_prompt(context) is None


@pytest.mark.asyncio
async def test_binding_does_not_copy_a_mentioned_members_binding() -> None:
    service = _PlayerService()
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        PortableQuerySessions(),
    )
    target = ActorRef(
        Platform.QQ_OFFICIAL,
        "target-openid",
        "member",
        "group-openid",
    )
    context = _context("绑定米米号", mentions=(target,))

    reply = cast(
        "PortableReply",
        await operations["seer.player.bind"](context.text, context),
    )

    assert "仅超级管理员" in _text(reply)
    assert service.bound == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", ["700001", "别名"])
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_superuser_binds_explicit_player_to_mentioned_member(
    reference: str,
    platform: Platform,
) -> None:
    service = _PlayerService()
    features = cast(
        "Any",
        SimpleNamespace(
            is_actor_superuser=lambda _actor: True,
        ),
    )
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        PortableQuerySessions(),
        features,
    )
    target = ActorRef(platform, "target-openid", "member", "group-openid")
    context = _context(
        f"绑定米米号{reference}",
        mentions=(target,),
        platform=platform,
    )
    reply = cast(
        "PortableReply",
        await operations["seer.player.bind"](context.text, context),
    )
    assert "player:700001" in _text(reply)
    assert service.bound == [(target, 700001)]
    reply.delivered()
    assert service.returned == [(context.message.actor, 700001)]


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", ["y", "n", "0"])
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_existing_binding_waits_for_explicit_confirmation(
    selection: str,
    platform: Platform,
) -> None:
    service = _PlayerService(replacement=True)
    sessions = PortableQuerySessions()
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        sessions,
    )
    context = _context("绑定米米号别名", platform=platform)

    reply = cast(
        "PortableReply",
        await operations["seer.player.bind"](context.text, context),
    )

    assert "当前默认米米号：600001" in _text(reply)
    assert "已查到米米号：700001（tester）" in _text(reply)
    assert "回复“是”或“y”确认" in _text(reply)
    assert service.replacement_choices == []
    assert service.returned == []
    selected = await sessions.select(selection, context, allow_deferred=True)
    assert selected is not None
    assert service.replacement_choices == (
        [(context.message.actor, 700001)] if selection == "y" else []
    )
    assert service.returned == []
    if selection != "0":
        selected = cast("PortableReply", selected)
        selected.delivered()
        assert service.returned == [(context.message.actor, 700001)]


@pytest.mark.asyncio
async def test_binding_replacement_rejects_numeric_and_other_member_choice() -> None:
    service = _PlayerService(replacement=True)
    sessions = PortableQuerySessions()
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        sessions,
    )
    context = _context("绑定米米号700001")
    await operations["seer.player.bind"](context.text, context)

    invalid = await sessions.select("1", context, allow_deferred=True)
    assert isinstance(invalid, OutboundMessage)
    assert "请回复“是”或“否”" in cast("TextPart", invalid.parts[0]).text
    stranger = _context("y", actor_id="another-member")
    assert await sessions.select("y", stranger, allow_deferred=True) is None
    assert service.replacement_choices == []
    assert sessions.has_active_session(context)
    assert await sessions.select("是", context, allow_deferred=True) is not None
    assert service.replacement_choices == [(context.message.actor, 700001)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reference", "count", "expected"),
    [
        ("", 1, "未找到该米米号"),
        ("700001", 2, "请一次只 @ 一名成员"),
    ],
)
async def test_admin_binding_rejects_missing_account_or_multiple_recipients(
    reference: str,
    count: int,
    expected: str,
) -> None:
    service = _PlayerService()
    features = cast("Any", SimpleNamespace(is_actor_superuser=lambda _actor: True))
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        PortableQuerySessions(),
        features,
    )
    mentions = tuple(
        ActorRef(Platform.QQ_OFFICIAL, f"member-{i}") for i in range(count)
    )
    context = _context(f"绑定米米号{reference}", mentions=mentions)
    reply = cast(
        "PortableReply",
        await operations["seer.player.bind"](context.text, context),
    )
    assert expected in _text(reply)
    assert service.bound == []


@pytest.mark.asyncio
async def test_player_query_accepts_configured_alias() -> None:
    service = _PlayerService()
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        PortableQuerySessions(),
    )
    context = _context("米米号别名")

    reply = cast(
        "PortableReply",
        await operations["seer.player.query"](context.text, context),
    )

    assert "player:700001" in _text(reply)
    reply.delivered()


@pytest.mark.asyncio
async def test_default_shortcut_uses_callers_openid_binding() -> None:
    service = _PlayerService()
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        PortableQuerySessions(),
    )
    context = _context("收集")

    reply = cast(
        "PortableReply",
        await operations["seer.player.default"](context.text, context),
    )

    part = reply.message.parts[0]
    assert isinstance(part, TextPart)
    assert part.text == "caller-openid:collection:600001"
    assert reply.follow_up is None


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("entry", ["direct", "menu"])
@pytest.mark.parametrize("queued", [False, True])
@pytest.mark.parametrize(
    "result",
    [
        QueryReply(text="result"),
        QueryReply(leading_text="player", image_error="image failed", complete=False),
        QueryReply(text="partial result", image_error="image failed", complete=False),
        QueryReply(leading_text="player", image=b"image-bytes", text="result"),
    ],
)
async def test_player_shortcut_feedback_uses_shared_delivery_template(
    monkeypatch: pytest.MonkeyPatch,
    platform: Platform,
    entry: str,
    result: QueryReply,
    *,
    queued: bool,
) -> None:
    service = _PlayerService()
    completed: list[bool] = []

    async def shortcut(*_args: object, **_kwargs: object) -> QueryReply:
        await send_request_feedback(queued=queued)
        completed.append(True)
        return result

    query = AsyncMock(side_effect=shortcut)
    monkeypatch.setattr(service, "shortcut", query)
    sessions = PortableQuerySessions()
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        sessions,
    )
    context = _context("巅峰700002", platform=platform)
    if entry == "direct":
        reply = await operations["seer.player.default"](context.text, context)
    else:
        initial = cast(
            "PortableReply",
            await operations["seer.player.query"]("米米号700002", context),
        )
        initial.delivered()
        reply = await sessions.select("巅峰", context, allow_deferred=True)
    assert isinstance(reply, PortableReply)
    expected_feedback = "已加入队列" if queued else "巅峰之战正在查询"
    assert expected_feedback in _text(reply)
    assert not completed
    query.assert_awaited_once()
    assert query.await_args is not None
    command, actor = query.await_args.args
    assert (command.kind, command.player_id, actor) == (
        "peak",
        700002,
        context.message.actor,
    )
    assert query.await_args.kwargs["conversation"] == context.message.conversation
    assert reply.follow_up is not None
    reply.delivered()
    assert await reply.follow_up() == result.to_outbound()
    assert completed == [True]
    if entry == "menu":
        assert sessions.has_active_session(context)


@pytest.mark.asyncio
async def test_shared_shortcut_without_binding_does_not_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _PlayerService()
    query = AsyncMock()
    monkeypatch.setattr(service, "shortcut", query)
    resolver = PlayerIdResolver(lambda *_: None, lambda _: None)
    operation = build_portable_player_operations(
        cast("PlayerService", service),
        resolver,
        PortableQuerySessions(),
    )["seer.player.default"]
    context = _context("收集")
    reply = await operation(context.text, context)
    assert isinstance(reply, PortableReply)
    assert "尚未绑定米米号" in _text(reply)
    query.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["direct", "menu"])
async def test_failed_player_progress_delivery_cancels_pending_query(
    monkeypatch: pytest.MonkeyPatch,
    entry: str,
) -> None:
    service = _PlayerService()
    completed: list[bool] = []

    async def shortcut(*_args: object, **_kwargs: object) -> QueryReply:
        await send_request_feedback(queued=True)
        completed.append(True)
        return QueryReply(text="must not finish")

    monkeypatch.setattr(service, "shortcut", AsyncMock(side_effect=shortcut))
    sessions = PortableQuerySessions()
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        sessions,
    )
    context = _context("收集700002")
    if entry == "direct":
        reply = await operations["seer.player.default"](context.text, context)
    else:
        initial = cast(
            "PortableReply",
            await operations["seer.player.query"]("米米号700002", context),
        )
        initial.delivered()
        reply = await sessions.select("收集", context, allow_deferred=True)
    assert isinstance(reply, PortableReply)
    assert reply.follow_up is not None
    reply.delivery_failed()
    with pytest.raises(asyncio.CancelledError):
        await reply.follow_up()
    assert not completed
