# SPDX-License-Identifier: MIT
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

HELP_HINT_GROUP_WINDOW_SECONDS = 60.0
HELP_HINT_GROUP_MAX_PER_WINDOW = 3


class PokeLikeEvent(Protocol):
    self_id: int
    target_id: int


class HelpHintLimiter:
    def __init__(
        self,
        *,
        window_seconds: float = HELP_HINT_GROUP_WINDOW_SECONDS,
        max_per_window: int = HELP_HINT_GROUP_MAX_PER_WINDOW,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.window_seconds = window_seconds
        self.max_per_window = max_per_window
        self._clock = clock
        self._timestamps: defaultdict[int, deque[float]] = defaultdict(deque)

    def can_send(self, group_id: int) -> bool:
        now = self._clock()
        timestamps = self._timestamps[group_id]
        while timestamps and now - timestamps[0] >= self.window_seconds:
            timestamps.popleft()

        if len(timestamps) >= self.max_per_window:
            return False

        timestamps.append(now)
        return True


_help_hint_limiter = HelpHintLimiter()


def is_poke_at_bot(event: PokeLikeEvent) -> bool:
    return event.target_id == event.self_id


def can_send_group_help_hint(group_id: int | None) -> bool:
    if group_id is None:
        return True
    return _help_hint_limiter.can_send(group_id)


__all__ = [
    "HELP_HINT_GROUP_MAX_PER_WINDOW",
    "HELP_HINT_GROUP_WINDOW_SECONDS",
    "HelpHintLimiter",
    "can_send_group_help_hint",
    "is_poke_at_bot",
]
