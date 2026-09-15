from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.player_references import PlayerReferenceChoice
from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.services.portable_player_commands import (
    build_portable_player_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
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
    PlayerQueryResult,
)
from ironsbot.services.seer.query_result import QueryReply

if TYPE_CHECKING:
    from ironsbot.services.portable_reply import PortableReply
    from ironsbot.services.seer.player_service import PlayerService
    from ironsbot.services.seer.player_shortcut_contracts import (
        PlayerShortcutCommand,
    )


class _PlayerService:
    def __init__(self, *, replacement: bool = False) -> None:
        self.queried: list[int] = []
        self.returned: list[tuple[ActorRef, int]] = []
        self.refreshed: list[int] = []
        self.bound: list[tuple[ActorRef, int]] = []
        self.replacement = replacement
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
            pending=_pending(player_id),
            offer_binding=explicit,
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


def _pending(player_id: int) -> PendingPlayerQuery:
    return PendingPlayerQuery(
        player_id=player_id,
        user_info=SimpleNamespace(nick="tester"),
        more_info=SimpleNamespace(),
        player_message=f"player:{player_id}",
        section_plan=PlayerQuerySectionPlan(
            show_local_rank=False,
            has_collection=True,
            needs_peak_section=True,
            has_autocard_rank=True,
            needs_online_info=False,
            local_rank_enabled=False,
        ),
    )


def _context(
    text: str,
    *,
    actor_id: str = "caller-openid",
    mentions: tuple[ActorRef, ...] = (),
    platform: Platform = Platform.QQ_OFFICIAL,
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
async def test_binding_selection_rechecks_reference_visibility() -> None:
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
    context = _context("绑定米米号玩家")
    await operations["seer.player.bind"](context.text, context)
    choices = ()
    reply = await sessions.select("1", context, allow_deferred=True)
    assert isinstance(reply, OutboundMessage)
    assert "已不可用" in cast("TextPart", reply.parts[0]).text
    assert not service.bound


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
    assert "绑定米米号700002" in _text(reply)
    assert service.returned == []
    assert service.refreshed == []
    reply.delivered()
    assert service.returned == [(context.message.actor, 700002)]
    assert service.refreshed == [700002]

    selected = await sessions.select("1", context)
    assert selected is not None
    part = selected.parts[0]
    assert isinstance(part, TextPart)
    assert part.text == "caller-openid:collection:700002"


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("selection", ["y", "n", "4", "5", "button", "0"])
async def test_first_binding_confirmation_reuses_query_and_delivery(
    platform: Platform, selection: str,
) -> None:
    service = _PlayerService()
    sessions = PortableQuerySessions()
    operations = build_portable_player_operations(
        cast("PlayerService", service), _resolver(), sessions,
    )
    context = _context("米米号700002", platform=platform)
    reply = cast(
        "PortableReply", await operations["seer.player.query"](context.text, context),
    )
    assert not service.bound
    reply.delivered()
    prompt = reply.message.prompt
    assert prompt is not None
    action = prompt.action_data(prompt.choices[3])
    selected = await sessions.select(
        action if selection == "button" else selection, context,
    )
    assert isinstance(selected, OutboundMessage)
    assert service.bound == (
        [(context.message.actor, 700002)]
        if selection in {"y", "4", "button"} else []
    )
    assert service.queried == [700002]
    assert service.returned == [(context.message.actor, 700002)]
    assert service.refreshed == [700002]
    assert not sessions.recognizes_response("y", context)
    assert await sessions.select_action(action, context) is None
    if selection == "0":
        assert sessions.active_prompt(context) is None
    else:
        assert sessions.recognizes_response("收集", context)
        assert await sessions.select("收集", context) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", ["4", "战队"])
async def test_player_query_menu_includes_available_shared_extension(
    selection: str,
) -> None:
    service = _PlayerService()
    sessions = PortableQuerySessions()
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
    features = cast(
        "Any",
        SimpleNamespace(
            is_feature_allowed=lambda *_args: True,
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

    reply = cast(
        "PortableReply",
        await operations["seer.player.query"](context.text, context),
    )

    assert "4. 【战队】" in _text(reply)
    selected = await sessions.select(selection, context)
    assert selected is not None
    part = selected.parts[0]
    assert isinstance(part, TextPart)
    assert part.text == "team detail"


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("inputs", [("收集", "巅峰", "群星牌"), ("1", "2", "3")])
async def test_player_detail_template_supports_repeated_named_and_numeric_choices(
    platform: Platform, inputs: tuple[str, str, str],
) -> None:
    service = _PlayerService()
    sessions = PortableQuerySessions()
    operations = build_portable_player_operations(
        cast("PlayerService", service), _resolver(), sessions,
    )
    context = _context("米米号700002", platform=platform)
    await operations["seer.player.query"](context.text, context)
    for text, kind in zip(inputs, ("collection", "peak", "autocard"), strict=True):
        assert sessions.recognizes_response(text, context)
        reply = await sessions.select(text, context)
        assert isinstance(reply, OutboundMessage)
        assert f":{kind}:700002" in cast("TextPart", reply.parts[0]).text
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
    reference: str, platform: Platform,
) -> None:
    service = _PlayerService()
    features = cast("Any", SimpleNamespace(
        is_actor_superuser=lambda _actor: True,
    ))
    operations = build_portable_player_operations(
        cast("PlayerService", service), _resolver(), PortableQuerySessions(), features,
    )
    target = ActorRef(platform, "target-openid", "member", "group-openid")
    context = _context(
        f"绑定米米号{reference}", mentions=(target,), platform=platform,
    )
    reply = cast(
        "PortableReply", await operations["seer.player.bind"](context.text, context),
    )
    assert "player:700001" in _text(reply)
    assert service.bound == [(target, 700001)]
    reply.delivered()
    assert service.returned == [(context.message.actor, 700001)]


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", ["1", "2", "0"])
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_existing_binding_waits_for_explicit_confirmation(
    selection: str, platform: Platform,
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

    assert "确认换绑" in _text(reply)
    assert service.replacement_choices == []
    assert service.returned == []
    selected = await sessions.select(selection, context, allow_deferred=True)
    assert selected is not None
    assert service.replacement_choices == (
        [(context.message.actor, 700001)] if selection == "1" else []
    )
    assert service.returned == []
    if selection != "0":
        selected = cast("PortableReply", selected)
        selected.delivered()
        assert service.returned == [(context.message.actor, 700001)]


@pytest.mark.asyncio
@pytest.mark.parametrize(("reference", "count", "expected"), [
    ("", 1, "未找到该米米号"),
    ("700001", 2, "请一次只 @ 一名成员"),
])
async def test_admin_binding_rejects_missing_account_or_multiple_recipients(
    reference: str, count: int, expected: str,
) -> None:
    service = _PlayerService()
    features = cast("Any", SimpleNamespace(is_actor_superuser=lambda _actor: True))
    operations = build_portable_player_operations(
        cast("PlayerService", service), _resolver(), PortableQuerySessions(), features,
    )
    mentions = tuple(
        ActorRef(Platform.QQ_OFFICIAL, f"member-{i}") for i in range(count)
    )
    context = _context(f"绑定米米号{reference}", mentions=mentions)
    reply = cast(
        "PortableReply", await operations["seer.player.bind"](context.text, context),
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
        "OutboundMessage",
        await operations["seer.player.default"](context.text, context),
    )

    part = reply.parts[0]
    assert isinstance(part, TextPart)
    assert part.text == "caller-openid:collection:600001"
