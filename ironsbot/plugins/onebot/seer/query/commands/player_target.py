# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve player-query targets from references, bindings, or one @ member."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.runtime.message_input import message_input_context
from ironsbot.services.seer.player_id_resolver import (
    PlayerIdResolution,
    PlayerIdResolver,
    PlayerReferenceLookup,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from nonebot.adapters.onebot.v11 import MessageEvent

    from ironsbot.core.platform import ActorRef
    from ironsbot.services.identity.player_accounts import PlayerAccountRegistry


def event_player_reference_lookup(
    accounts: PlayerAccountRegistry,
) -> PlayerReferenceLookup:
    """Adapt scoped configured aliases to the platform-neutral resolver port."""

    return lambda reference, conversation: accounts.resolve_player_id(
        reference,
        conversation=conversation,
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
