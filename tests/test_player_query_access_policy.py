# SPDX-License-Identifier: MIT
"""Query access is based on the caller and the original target syntax."""

from __future__ import annotations

from typing import cast

import pytest

from ironsbot.config.models.seer import PlayerBindingConfig
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.player_references import PlayerReferenceChoice
from ironsbot.services.player_reference_selection import select_player_reference
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.seer.player_id_resolver import (
    PlayerIdResolver,
    PlayerTargetSource,
)

OWNER_ID = 700001
OTHER_ID = 700002
OWNER = ActorRef(Platform.ONEBOT, "owner")
CALLER = ActorRef(Platform.ONEBOT, "caller")
OTHER_ADMIN = ActorRef(Platform.ONEBOT, "other-admin")
GROUP = ConversationRef(Platform.ONEBOT, "group", "test-group")


def _context(
    actor: ActorRef = CALLER, *, mentions: tuple[ActorRef, ...] = ()
) -> MessageInputContext:
    return MessageInputContext(
        IncomingMessageRef(
            platform=actor.platform,
            actor=actor,
            conversation=GROUP,
            message_id="query-message",
            text="米米号",
            direct_mentions=mentions,
        ),
        mentions_bot=False,
    )


def _resolver(config: PlayerBindingConfig, *, bound: bool = False) -> PlayerIdResolver:
    def binding(actor: ActorRef) -> int | None:
        if actor.id == OWNER.id:
            return OWNER_ID
        if actor.id == OTHER_ADMIN.id:
            return OTHER_ID
        return OTHER_ID if bound else None

    def lookup(reference: str, _conversation: ConversationRef) -> int | None:
        return (
            int(reference)
            if reference.isdecimal()
            else {"甲": OWNER_ID, "乙": OTHER_ID}.get(reference)
        )

    return PlayerIdResolver(
        lookup,
        binding,
        binding_config=config,
        superuser_actors=lambda: (OWNER, OTHER_ADMIN),
        reference_search=lambda *_: (
            PlayerReferenceChoice(OWNER_ID, "甲玩家"),
            PlayerReferenceChoice(OTHER_ID, "乙玩家"),
        ),
    )


@pytest.mark.parametrize("allowed", [0, 1])
@pytest.mark.parametrize(
    "source,field",
    [
        ("numeric", "allow_unbound_numeric_queries"),
        ("alias", "allow_unbound_alias_queries"),
        ("member", "allow_unbound_member_queries"),
    ],
)
def test_unbound_query_switches(source: str, field: str, allowed: int) -> None:
    config = PlayerBindingConfig.model_validate(
        {field: bool(allowed), "allow_others_superuser_bound_shortcuts": True}
    )
    resolver = _resolver(config)
    assert (
        resolver.query_access_error(
            CALLER, OTHER_ID, cast("PlayerTargetSource", source)
        )
        is None
    ) is bool(allowed)
    assert resolver.resolve(_context(), None).player_id is None


@pytest.mark.parametrize("allowed", [0, 1])
def test_superuser_bound_shortcuts_are_separate_from_numeric(
    allowed: int,
) -> None:
    resolver = _resolver(
        PlayerBindingConfig(allow_others_superuser_bound_shortcuts=bool(allowed)),
        bound=True,
    )
    assert resolver.resolve_reference(str(OWNER_ID), CALLER, GROUP).error is None
    assert (resolver.resolve_reference("甲", CALLER, GROUP).error is None) is bool(
        allowed
    )
    assert (
        resolver.resolve(_context(CALLER, mentions=(OWNER,)), None).error is None
    ) is bool(allowed)
    assert resolver.resolve_reference("甲", OWNER, GROUP).error is None
    assert (resolver.resolve_reference("甲", OTHER_ADMIN, GROUP).error is None) is bool(
        allowed
    )


@pytest.mark.asyncio
async def test_partial_alias_choice_rechecks_selected_player_before_query() -> None:
    resolver = _resolver(PlayerBindingConfig(), bound=True)
    sessions = PortableQuerySessions()
    calls: list[int] = []

    async def query(player_id: int, _context: MessageInputContext) -> OutboundMessage:
        calls.append(player_id)
        return OutboundMessage.from_text("queried")

    context = _context()
    await select_player_reference(
        "玩家",
        context,
        resolver,
        sessions,
        query,
        title="选择玩家",
        enforce_query_access=True,
    )
    blocked = await sessions.select("1", context, allow_deferred=True)
    assert isinstance(blocked, OutboundMessage)
    assert isinstance(blocked.parts[0], TextPart)
    assert "完整数字" in blocked.parts[0].text
    assert calls == []


def test_binding_config_requires_strict_booleans() -> None:
    for field in (
        "allow_unbound_numeric_queries",
        "allow_unbound_alias_queries",
        "allow_unbound_member_queries",
        "allow_others_superuser_bound_shortcuts",
    ):
        with pytest.raises(ValueError):
            PlayerBindingConfig.model_validate({field: "false"})


def test_verified_cross_platform_owner_keeps_own_shortcut() -> None:
    official_owner = ActorRef(
        Platform.QQ_OFFICIAL,
        "owner-openid",
        "member",
        "official-group",
        account_id="example-app",
    )
    resolver = PlayerIdResolver(
        lambda _reference, _conversation: OWNER_ID,
        lambda actor: OWNER_ID if actor in {OWNER, official_owner} else None,
        binding_config=PlayerBindingConfig(),
        superuser_actors=lambda: (OWNER,),
        same_actor=lambda left, right: (
            left in {OWNER, official_owner} and right in {OWNER, official_owner}
        ),
    )

    assert resolver.resolve_reference("别名", official_owner, GROUP).error is None
    assert "完整数字" in (resolver.resolve_reference("别名", CALLER, GROUP).error or "")
