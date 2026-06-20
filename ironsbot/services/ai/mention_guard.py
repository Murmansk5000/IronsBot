from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

from ironsbot.services.ai.mentions import mentions_bot
from ironsbot.services.ai.permissions import is_allowed as is_ai_allowed

if TYPE_CHECKING:
    from collections.abc import Callable


class GuardReplyLimiter:
    def __init__(
        self,
        *,
        window_seconds: float,
        max_per_window: int,
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


async def should_guard_non_ai_group_mention(event: MessageEvent) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False

    if not mentions_bot(event):
        return False

    return not is_ai_allowed(event)
