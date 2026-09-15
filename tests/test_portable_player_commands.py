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
        assert accepted
        assert replacing_existing
        self.replacement_choices.append((actor, pending.player_id))
        pending.player_message = (
            f"replaced:{pending.player_id}\n{pending.player_message}"
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
        return {"别名": 700001}.get(reference)

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
async def test_player_query_menu_includes_available_shared_extension() -> None:
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
    selected = await sessions.select("4", context)
    assert selected is not None
    part = selected.parts[0]
    assert isinstance(part, TextPart)
    assert part.text == "team detail"


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
    operations = build_portable_player_operations(
        cast("PlayerService", service),
        _resolver(),
        PortableQuerySessions(),
    )
    context = _context("绑定米米号别名")

    reply = cast(
        "PortableReply",
        await operations["seer.player.bind"](context.text, context),
    )

    assert "replaced:700001" in _text(reply)
    assert service.replacement_choices == [(context.message.actor, 700001)]


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
