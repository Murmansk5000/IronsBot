# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field


@dataclass(slots=True)
class InMemoryRateLimiter:
    _last_at: dict[tuple[str, int], float] = field(default_factory=dict)

    def remaining_seconds(
        self,
        namespace: str,
        subject_id: int,
        cooldown_seconds: float,
        *,
        exempt: bool = False,
    ) -> int:
        if exempt or cooldown_seconds <= 0:
            return 0

        now = time.monotonic()
        last_at = self._last_at.get((namespace, subject_id))
        if last_at is None:
            return 0

        remaining = cooldown_seconds - (now - last_at)
        if remaining <= 0:
            return 0

        return max(1, math.ceil(remaining))

    def penalize(
        self,
        namespace: str,
        subject_id: int,
        cooldown_seconds: float,
        *,
        exempt: bool = False,
    ) -> None:
        if exempt or cooldown_seconds <= 0:
            return

        self._last_at[(namespace, subject_id)] = time.monotonic()

    def clear(self, namespace: str | None = None) -> None:
        if namespace is None:
            self._last_at.clear()
            return

        for key in list(self._last_at):
            if key[0] == namespace:
                del self._last_at[key]


rate_limiter = InMemoryRateLimiter()


def peek_user_rate_limit(
    namespace: str,
    user_id: int,
    cooldown_seconds: float,
    *,
    exempt: bool = False,
) -> int:
    return rate_limiter.remaining_seconds(
        namespace,
        user_id,
        cooldown_seconds,
        exempt=exempt,
    )


def penalize_user_rate_limit(
    namespace: str,
    user_id: int,
    cooldown_seconds: float,
    *,
    exempt: bool = False,
) -> None:
    rate_limiter.penalize(
        namespace,
        user_id,
        cooldown_seconds,
        exempt=exempt,
    )
