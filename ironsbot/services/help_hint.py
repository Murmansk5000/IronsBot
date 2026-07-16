# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Protocol

from ironsbot.config.loader import get_app_config
from ironsbot.shared.messaging.rate_limits import hit_sliding_window_rate_limit

HELP_HINT_RATE_LIMIT_NAMESPACE = "help_hint"


class PokeLikeEvent(Protocol):
    self_id: int
    target_id: int


def is_poke_at_bot(event: PokeLikeEvent) -> bool:
    return event.target_id == event.self_id


def get_group_poke_reply(group_id: int | None) -> str | None:
    if group_id is None:
        return None

    config = get_app_config()
    aliases = config.feature.group_aliases
    for raw_group, message in config.runtime.help.poke_replies.items():
        resolved_group = aliases.get(raw_group)
        if resolved_group is None and raw_group.isdigit():
            resolved_group = int(raw_group)
        if resolved_group == group_id:
            return message
    return None


def can_send_group_help_hint(
    group_id: int | None,
    *,
    now: float | None = None,
) -> bool:
    if group_id is None:
        return True

    config = get_app_config().runtime.help
    return (
        hit_sliding_window_rate_limit(
            HELP_HINT_RATE_LIMIT_NAMESPACE,
            group_id,
            window_seconds=config.hint_window_seconds,
            max_events=config.hint_max_per_window,
            now=now,
        )
        >= 0
    )


__all__ = [
    "HELP_HINT_RATE_LIMIT_NAMESPACE",
    "can_send_group_help_hint",
    "get_group_poke_reply",
    "is_poke_at_bot",
]
