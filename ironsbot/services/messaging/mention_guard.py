# SPDX-License-Identifier: MIT
"""Per-user response policy for direct mentions in non-AI groups."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Final

from ironsbot.services.messaging.rate_limits import SlidingWindowRateLimiter

MENTION_REPEAT_WINDOW_SECONDS: Final = 60.0
MENTION_INITIAL_WINDOW_SECONDS: Final = 600.0
MENTION_INITIAL_MAX_RESPONSES: Final = 3
REPEATED_MENTION_MESSAGE: Final = "该指令重复发送；后续重复不再提醒。"


@dataclass(frozen=True, slots=True)
class MentionGuardDecision:
    reply: str | None = None
    should_send_help: bool = False


@dataclass(slots=True)
class _MentionCycle:
    started_at: float
    duplicate_notified: bool = False


@dataclass(slots=True)
class MentionGuardService:
    """Reply once, warn once, then stay silent for each user-minute cycle."""

    limiter: SlidingWindowRateLimiter = field(
        default_factory=SlidingWindowRateLimiter
    )
    _cycles: dict[int, _MentionCycle] = field(default_factory=dict)

    def admit(self, user_id: int, *, now: float | None = None) -> MentionGuardDecision:
        current_time = monotonic() if now is None else now
        self._prune_cycles(current_time)
        if cycle := self._cycles.get(user_id):
            if not cycle.duplicate_notified:
                cycle.duplicate_notified = True
                return MentionGuardDecision(REPEATED_MENTION_MESSAGE)
            return MentionGuardDecision(None)

        remaining = self.limiter.hit(
            "non_ai_mention_guard",
            user_id,
            window_seconds=MENTION_INITIAL_WINDOW_SECONDS,
            max_events=MENTION_INITIAL_MAX_RESPONSES,
            now=current_time,
        )
        if remaining < 0:
            return MentionGuardDecision(None)

        self._cycles[user_id] = _MentionCycle(started_at=current_time)
        return MentionGuardDecision(should_send_help=True)

    def _prune_cycles(self, now: float) -> None:
        self._cycles = {
            user_id: cycle
            for user_id, cycle in self._cycles.items()
            if now - cycle.started_at < MENTION_REPEAT_WINDOW_SECONDS
        }
