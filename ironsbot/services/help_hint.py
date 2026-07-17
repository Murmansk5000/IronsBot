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


def _get_poke_reply(
    target_id: int | None,
    *,
    aliases: dict[str, int],
    replies: dict[str, str],
) -> str | None:
    if target_id is None:
        return None

    for raw_target, message in replies.items():
        resolved_target = aliases.get(raw_target)
        if resolved_target is None and raw_target.isdigit():
            resolved_target = int(raw_target)
        if resolved_target == target_id:
            return message
    return None


def get_group_poke_reply(group_id: int | None) -> str | None:
    config = get_app_config()
    return _get_poke_reply(
        group_id,
        aliases=config.feature.group_aliases,
        replies=config.runtime.help.poke_replies,
    )


def get_user_poke_reply(user_id: int) -> str | None:
    config = get_app_config()
    return _get_poke_reply(
        user_id,
        aliases=config.feature.user_aliases,
        replies=config.runtime.help.poke_user_replies,
    )


def get_poke_reply(*, group_id: int | None, user_id: int) -> str | None:
    return get_user_poke_reply(user_id) or get_group_poke_reply(group_id)


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
    "get_poke_reply",
    "get_user_poke_reply",
    "is_poke_at_bot",
]
