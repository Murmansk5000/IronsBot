# SPDX-License-Identifier: MIT
"""Bounded reply sequence allocation for QQ Official messages."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from time import monotonic


@dataclass(frozen=True, slots=True)
class ReplySequenceAllocation:
    sequence: int | None
    reason: str | None = None


@dataclass(slots=True)
class _TrackedReply:
    count: int
    first_seen: float


class QQOfficialReplySequenceAllocator:
    """Allocate each passive reply sequence once within the platform window."""

    def __init__(
        self,
        *,
        limit: int = 4,
        ttl_seconds: float = 3600,
        max_tracked_messages: int = 10_000,
    ) -> None:
        if limit < 1 or ttl_seconds <= 0 or max_tracked_messages < 1:
            msg = "QQ reply sequence limits must be positive"
            raise ValueError(msg)
        self._limit = limit
        self._ttl_seconds = ttl_seconds
        self._max_tracked_messages = max_tracked_messages
        self._tracked: OrderedDict[str, _TrackedReply] = OrderedDict()
        self._lock = Lock()

    def allocate(self, message_id: str) -> ReplySequenceAllocation:
        now = monotonic()
        with self._lock:
            tracked = self._tracked.get(message_id)
            if tracked is not None and now - tracked.first_seen > self._ttl_seconds:
                self._tracked.move_to_end(message_id)
                return ReplySequenceAllocation(None, "expired")
            if tracked is not None:
                if tracked.count >= self._limit:
                    return ReplySequenceAllocation(None, "limit_exceeded")
                tracked.count += 1
                self._tracked.move_to_end(message_id)
                return ReplySequenceAllocation(tracked.count)

            while len(self._tracked) >= self._max_tracked_messages:
                self._tracked.popitem(last=False)
            self._tracked[message_id] = _TrackedReply(count=1, first_seen=now)
            return ReplySequenceAllocation(1)
