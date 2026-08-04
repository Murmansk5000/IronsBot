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


def resolve_player_target(
    event: MessageEvent,
    *,
    numeric_player_id: int | None,
    binding_for_user: Callable[[ActorRef], int | None],
    allow_default_binding: bool = True,
) -> PlayerIdResolution:
    """Adapt current OneBot input to the shared player-ID resolver."""
    context = message_input_context(event)
    resolver = PlayerIdResolver(
        lambda _reference, _conversation: numeric_player_id,
        binding_for_user,
    )
    return resolver.resolve(
        context,
        "resolved-player-reference" if numeric_player_id is not None else None,
        allow_default_binding=allow_default_binding,
    )
