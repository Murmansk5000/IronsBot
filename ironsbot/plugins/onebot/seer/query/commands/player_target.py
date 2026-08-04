# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve player-query targets from references, bindings, or one @ member."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import MessageEvent

from ironsbot.runtime.message_input import message_input_context
from ironsbot.runtime.onebot_context import event_group_id
from ironsbot.services.seer.player_id_resolver import (
    PlayerIdResolution,
    PlayerIdResolver,
    PlayerReferenceLookup,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from nonebot.adapters import Event

    from ironsbot.config.player_accounts import PlayerAccountRegistry
    from ironsbot.core.platform import ActorRef


def resolve_event_player_reference(
    accounts: PlayerAccountRegistry,
    event: Event,
    reference: object,
) -> int | None:
    """Resolve one numeric or configured player reference in event scope."""

    return accounts.resolve_player_id(
        reference,
        group_id=event_group_id(event) if isinstance(event, MessageEvent) else None,
    )


def event_player_reference_lookup(
    accounts: PlayerAccountRegistry,
    event: Event,
) -> PlayerReferenceLookup:
    """Adapt scoped configured aliases to the platform-neutral resolver port."""

    group_id = event_group_id(event) if isinstance(event, MessageEvent) else None
    return lambda reference, _conversation: accounts.resolve_player_id(
        reference,
        group_id=group_id,
    )


def resolve_player_target(
    event: MessageEvent,
    *,
    player_reference: str | None,
    reference_lookup: PlayerReferenceLookup,
    binding_for_user: Callable[[ActorRef], int | None],
    allow_default_binding: bool = True,
) -> PlayerIdResolution:
    """Adapt current OneBot input to the shared player-ID resolver."""
    context = message_input_context(event)
    resolver = PlayerIdResolver(
        reference_lookup,
        binding_for_user,
    )
    return resolver.resolve(
        context,
        player_reference,
        allow_default_binding=allow_default_binding,
    )
