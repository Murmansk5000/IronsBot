from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

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
from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.services.operations.request_feedback import send_request_feedback
from ironsbot.services.portable_player_commands import (
    build_portable_player_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.seer.player_binding import PlayerBindingState
from ironsbot.services.seer.player_detail_extensions import (
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

TARGET_PLAYER_ID = 700_002
ALIAS_PLAYER_ID = 700_001

if TYPE_CHECKING:
    from ironsbot.services.portable_reply import PortableReply
    from ironsbot.services.seer.player_service import PlayerService
    from ironsbot.services.seer.player_shortcut_contracts import (
        PlayerShortcutCommand,
    )


class _PlayerService:
    def __init__(self, *, replacement: bool = False) -> None:
        self.returned: list[tuple[ActorRef, int]] = []
        self.refreshed: list[int] = []
        self.bound: list[tuple[ActorRef, int]] = []
        self.replacement = replacement
        self.binding_choices: list[tuple[ActorRef, int, bool, bool]] = []

    async def query(
        self,
        player_id: int,
        *,
        actor: ActorRef,
        explicit: bool,
        conversation: ConversationRef | None,
    ) -> PlayerQueryResult:
        del actor, conversation
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
    ) -> PlayerQueryResult:
        del conversation
        self.bound.append((actor, player_id))
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
        self.binding_choices.append(
            (actor, pending.player_id, accepted, replacing_existing)
        )
        status = "accepted" if accepted else "declined"
        pending.player_message = (
            f"{status}:{pending.player_id}\n{pending.player_message}"
        )
        return status

    def binding_offer(
        self,
        pending: PendingPlayerQuery,
        *,
        replacement: PlayerBindingState | None = None,
    ) -> str:
        return f"bind:{pending.player_id}:replace={replacement is not None}"

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
) -> MessageInputContext:
    conversation = ConversationRef(Platform.QQ_OFFICIAL, "group", "group-openid")
    actor = ActorRef(
        Platform.QQ_OFFICIAL,
        actor_id,
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
        return {"别名": ALIAS_PLAYER_ID}.get(reference)

    return PlayerIdResolver(
        lookup,
        lambda actor: {
            "caller-openid": 600001,
            "target-openid": 800001,
        }.get(actor.id),
    )


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
    context = _context(f"米米号{TARGET_PLAYER_ID}")

    reply = cast(
        "PortableReply",
        await operations["seer.player.query"](context.text, context),
    )

    assert _text(reply) == f"bind:{TARGET_PLAYER_ID}:replace=False"
    reply = cast(
        "PortableReply",
        await sessions.select("否", context, allow_deferred=True),
    )
    assert f"player:{TARGET_PLAYER_ID}" in _text(reply)
    assert "1. 【收集】" in _text(reply)
    assert service.returned == []
    assert service.refreshed == []
    reply.delivered()
    assert service.returned == [(context.message.actor, TARGET_PLAYER_ID)]
    assert service.refreshed == [TARGET_PLAYER_ID]

    selected = cast(
        "PortableReply",
        await sessions.select("1", context, allow_deferred=True),
    )
    assert _text(selected) == f"caller-openid:collection:{TARGET_PLAYER_ID}"
    assert sessions.has_pending(context)
    exit_reply = await sessions.select("0", context)
    assert isinstance(exit_reply, OutboundMessage)
    exit_part = exit_reply.parts[0]
    assert isinstance(exit_part, TextPart)
    assert exit_part.text == "已退出米米号详情查询。"
    assert not sessions.has_pending(context)


@pytest.mark.asyncio
async def test_binding_accepts_one_mentioned_openid_binding() -> None:
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

    assert "player:800001" in _text(reply)
    assert service.bound == [(context.message.actor, 800001)]


@pytest.mark.asyncio
async def test_explicit_binding_confirms_an_existing_binding_replacement() -> None:
    service = _PlayerService(replacement=True)
    sessions = PortableQuerySessions()
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        sessions,
    )
    context = _context("绑定米米号别名")

    prompt = cast(
        "PortableReply",
        await operations["seer.player.bind"](context.text, context),
    )
    assert _text(prompt) == "bind:700001:replace=True"
    reply = cast(
        "PortableReply",
        await sessions.select("是", context, allow_deferred=True),
    )
    assert "accepted:700001" in _text(reply)
    assert service.binding_choices == [(context.message.actor, 700001, True, True)]


@pytest.mark.asyncio
async def test_player_query_accepts_configured_alias() -> None:
    service = _PlayerService()
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        PortableQuerySessions(),
    )
    context = _context("米米号别名")

    prompt = cast(
        "PortableReply",
        await operations["seer.player.query"](context.text, context),
    )
    assert "700001" in _text(prompt)


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

    assert _text(reply) == "caller-openid:collection:600001"


@pytest.mark.asyncio
async def test_player_shortcut_progress_and_result_share_portable_delivery() -> None:
    class _ProgressPlayerService(_PlayerService):
        async def shortcut(
            self,
            command: PlayerShortcutCommand,
            actor: ActorRef,
            *,
            conversation: ConversationRef | None,
        ) -> QueryReply:
            del conversation
            await send_request_feedback(queued=True)
            return QueryReply(text=f"{actor.id}:{command.kind}:{command.player_id}")

    service = _ProgressPlayerService()
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        PortableQuerySessions(),
    )
    context = _context("巅峰")

    reply = cast(
        "PortableReply",
        await operations["seer.player.default"](context.text, context),
    )

    assert "已加入队列" in _text(reply)
    assert reply.follow_up is not None
    await reply.commit_delivery()
    result = await reply.follow_up()
    assert isinstance(result, OutboundMessage)
    part = result.parts[0]
    assert isinstance(part, TextPart)
    assert part.text == "caller-openid:peak:600001"


@pytest.mark.asyncio
async def test_player_menu_filters_and_executes_extension_with_own_semantics() -> None:
    service = _PlayerService()
    sessions = PortableQuerySessions()
    context = _context(f"米米号{TARGET_PLAYER_ID}")
    extension_query = AsyncMock(
        return_value=QueryReply(text=f"lineup:{TARGET_PLAYER_ID}")
    )
    extensions = PlayerDetailExtensionRegistry()
    extensions.register(
        PlayerDetailExtensionAction(
            id="player.lineup",
            feature="player_lineup",
            label="阵容",
            aliases=("阵容",),
            command_help_id="player.lineup",
            query=extension_query,
            action=ActionDefinition("player.lineup", "阵容"),
        )
    )
    features = FeatureService(
        group_features={context.message.conversation: frozenset({"player_lineup"})},
        actor_features={},
        superusers=frozenset(),
    )
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        sessions,
        features,
        extensions,
    )

    await operations["seer.player.query"](context.text, context)
    menu = cast(
        "PortableReply",
        await sessions.select("否", context, allow_deferred=True),
    )

    assert "4. 【阵容】" in _text(menu)
    semantic = sessions.semantic_request(
        "4",
        context,
        action=ActionDefinition("fallback", "fallback"),
    )
    assert semantic is not None
    assert semantic.action.id == "player.lineup"
    assert semantic.target.key == str(TARGET_PLAYER_ID)

    result = cast(
        "PortableReply",
        await sessions.select("4", context, allow_deferred=True),
    )
    assert _text(result) == f"lineup:{TARGET_PLAYER_ID}"
    extension_query.assert_awaited_once()
    assert extension_query.await_args is not None
    assert extension_query.await_args.args[0].player_id == TARGET_PLAYER_ID


@pytest.mark.asyncio
async def test_player_extension_direct_command_is_a_portable_operation() -> None:
    service = _PlayerService()
    extension_query = AsyncMock(
        return_value=QueryReply(text=f"lineup:{ALIAS_PLAYER_ID}")
    )
    extensions = PlayerDetailExtensionRegistry()
    extensions.register(
        PlayerDetailExtensionAction(
            id="player.lineup",
            feature="player_lineup",
            label="阵容",
            aliases=("阵容",),
            command_help_id="private_player_lineup.query",
            query=extension_query,
            action=ActionDefinition("player.lineup", "阵容"),
        )
    )
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        PortableQuerySessions(),
        extensions=extensions,
    )
    context = _context("阵容别名")

    reply = cast(
        "PortableReply",
        await operations["private_player_lineup.query"](context.text, context),
    )

    assert _text(reply) == f"lineup:{ALIAS_PLAYER_ID}"
    extension_query.assert_awaited_once()
    assert extension_query.await_args is not None
    assert extension_query.await_args.args[0].player_id == ALIAS_PLAYER_ID
