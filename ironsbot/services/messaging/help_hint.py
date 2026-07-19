# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from ironsbot.services.messaging.rate_limits import SlidingWindowRateLimiter

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.core.features import HelpConfig


class PokeLikeEvent(Protocol):
    self_id: int
    target_id: int


def is_poke_at_bot(event: PokeLikeEvent) -> bool:
    return event.target_id == event.self_id


def _get_poke_reply(
    target_id: int | None,
    *,
    aliases: Mapping[str, int],
    replies: Mapping[str, str],
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


@dataclass(slots=True)
class HelpHintService:
    config: HelpConfig
    group_aliases: Mapping[str, int]
    user_aliases: Mapping[str, int]
    limiter: SlidingWindowRateLimiter = field(
        default_factory=SlidingWindowRateLimiter
    )

    def get_poke_reply(self, *, group_id: int | None, user_id: int) -> str | None:
        return _get_poke_reply(
            user_id,
            aliases=self.user_aliases,
            replies=self.config.poke_user_replies,
        ) or _get_poke_reply(
            group_id,
            aliases=self.group_aliases,
            replies=self.config.poke_replies,
        )

    def can_send(self, group_id: int | None, *, now: float | None = None) -> bool:
        if group_id is None:
            return True
        return (
            self.limiter.hit(
                "help_hint",
                group_id,
                window_seconds=self.config.hint_window_seconds,
                max_events=self.config.hint_max_per_window,
                now=now,
            )
            >= 0
        )
