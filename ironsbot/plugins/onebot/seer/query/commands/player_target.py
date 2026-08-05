# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve player-query targets from references, bindings, or one @ member."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.services.seer.player_id_resolver import (
    PLAYER_ID_RESOLVER_REQUIRED_ERROR,
)

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent

    from ironsbot.services.seer.player_id_resolver import (
        PlayerIdResolution,
        PlayerIdResolver,
    )


def resolve_player_target(
    event: MessageEvent,
    *,
    player_reference: str | None,
    resolver: PlayerIdResolver | None,
    allow_default_binding: bool = True,
) -> PlayerIdResolution:
    """Adapt current OneBot input to the shared player-ID resolver."""
    if resolver is None:
        raise RuntimeError(PLAYER_ID_RESOLVER_REQUIRED_ERROR)
    return resolver.resolve(
        message_input_context(event),
        player_reference,
        allow_default_binding=allow_default_binding,
    )
