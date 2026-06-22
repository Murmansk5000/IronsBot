# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from collections.abc import Hashable
from dataclasses import dataclass, field

RateLimitSubject = Hashable


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


@dataclass(slots=True)
class SlidingWindowRateLimiter:
    _events: dict[tuple[str, RateLimitSubject], deque[float]] = field(
        default_factory=lambda: defaultdict(deque)
    )

    def hit(  # noqa: PLR0913
        self,
        namespace: str,
        subject_id: RateLimitSubject,
        *,
        window_seconds: float,
        max_events: int,
        now: float | None = None,
        exempt: bool = False,
    ) -> int:
        if exempt or window_seconds <= 0 or max_events <= 0:
            return 1

        current_time = time.monotonic() if now is None else now
        timestamps = self._events[(namespace, subject_id)]
        self._trim(timestamps, cutoff=current_time - window_seconds)
        if len(timestamps) >= max_events:
            return -1

        timestamps.append(current_time)
        return max_events - len(timestamps)

    def clear(self, namespace: str | None = None) -> None:
        if namespace is None:
            self._events.clear()
            return

        for key in list(self._events):
            if key[0] == namespace:
                del self._events[key]

    @staticmethod
    def _trim(timestamps: deque[float], *, cutoff: float) -> None:
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()


rate_limiter = InMemoryRateLimiter()
sliding_window_rate_limiter = SlidingWindowRateLimiter()


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


def hit_sliding_window_rate_limit(  # noqa: PLR0913
    namespace: str,
    subject_id: RateLimitSubject,
    *,
    window_seconds: float,
    max_events: int,
    now: float | None = None,
    exempt: bool = False,
) -> int:
    return sliding_window_rate_limiter.hit(
        namespace,
        subject_id,
        window_seconds=window_seconds,
        max_events=max_events,
        now=now,
        exempt=exempt,
    )
