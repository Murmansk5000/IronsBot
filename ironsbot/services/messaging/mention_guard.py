# SPDX-License-Identifier: MIT
"""Per-user response policy for direct mentions in non-AI groups."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Protocol

from ironsbot.core.response_admission import (
    FeedbackOnce,
    ResponseAdmissionDecision,
)
from ironsbot.services.messaging.rate_limits import SlidingWindowRateLimiter


@dataclass(slots=True)
class _MentionCycle:
    started_at: float
    feedback: FeedbackOnce = field(default_factory=FeedbackOnce)


class MentionGuardConfig(Protocol):
    duplicate_window_seconds: float
    duplicate_message: str
    mention_initial_window_seconds: float
    mention_initial_max_responses: int


@dataclass(slots=True)
class MentionGuardService:
    """Reply once, warn once, then stay silent for each user-minute cycle."""

    config: MentionGuardConfig
    limiter: SlidingWindowRateLimiter = field(default_factory=SlidingWindowRateLimiter)
    _cycles: dict[int, _MentionCycle] = field(default_factory=dict)

    def admit(
        self,
        user_id: int,
        *,
        now: float | None = None,
    ) -> ResponseAdmissionDecision:
        current_time = monotonic() if now is None else now
        self._prune_cycles(current_time)
        if cycle := self._cycles.get(user_id):
            return ResponseAdmissionDecision(
                allowed=False,
                feedback=cycle.feedback.take(self.config.duplicate_message),
            )

        remaining = self.limiter.hit(
            "non_ai_mention_guard",
            user_id,
            window_seconds=self.config.mention_initial_window_seconds,
            max_events=self.config.mention_initial_max_responses,
            now=current_time,
        )
        if remaining < 0:
            return ResponseAdmissionDecision(allowed=False)

        self._cycles[user_id] = _MentionCycle(started_at=current_time)
        return ResponseAdmissionDecision(allowed=True)

    def _prune_cycles(self, now: float) -> None:
        self._cycles = {
            user_id: cycle
            for user_id, cycle in self._cycles.items()
            if now - cycle.started_at < self.config.duplicate_window_seconds
        }
