# SPDX-License-Identifier: MIT
from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Hashable
from dataclasses import dataclass, field

RateLimitSubject = Hashable


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


sliding_window_rate_limiter = SlidingWindowRateLimiter()


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
