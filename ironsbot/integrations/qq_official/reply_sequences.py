# SPDX-License-Identifier: MIT
"""Bounded passive-reply sequence allocation for QQ Official messages."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class ReplySequenceKey:
    conversation_kind: str
    conversation_id: str
    message_id: str


@dataclass(frozen=True, slots=True)
class ReplySequenceAllocation:
    sequence: int | None
    reason: str | None = None


@dataclass(slots=True)
class _TrackedReply:
    count: int
    expires_at: datetime


class QQOfficialReplySequenceAllocator:
    """Allocate unique ``msg_seq`` values without evicting live reply keys."""

    def __init__(
        self,
        *,
        max_tracked_messages: int = 10_000,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_tracked_messages < 1:
            msg = "QQ reply sequence tracking capacity must be positive"
            raise ValueError(msg)
        self._max_tracked_messages = max_tracked_messages
        self._clock = clock or (lambda: datetime.now(UTC))
        self._tracked: OrderedDict[ReplySequenceKey, _TrackedReply] = OrderedDict()
        self._lock = Lock()

    def allocate(
        self,
        key: ReplySequenceKey,
        *,
        expires_at: datetime,
        limit: int,
        count: int = 1,
    ) -> ReplySequenceAllocation:
        if limit < 1 or count < 1:
            msg = "QQ reply sequence reservation and limit must be positive"
            raise ValueError(msg)
        now = self._clock()
        with self._lock:
            self._prune_expired(now)
            if now >= expires_at:
                return ReplySequenceAllocation(None, "expired")

            tracked = self._tracked.get(key)
            if tracked is not None:
                if tracked.count + count > limit:
                    return ReplySequenceAllocation(None, "limit_exceeded")
                first_sequence = tracked.count + 1
                tracked.count += count
                tracked.expires_at = min(tracked.expires_at, expires_at)
                self._tracked.move_to_end(key)
                return ReplySequenceAllocation(first_sequence)

            if count > limit:
                return ReplySequenceAllocation(None, "limit_exceeded")
            if len(self._tracked) >= self._max_tracked_messages:
                return ReplySequenceAllocation(None, "capacity_exceeded")
            self._tracked[key] = _TrackedReply(count=count, expires_at=expires_at)
            return ReplySequenceAllocation(1)

    def _prune_expired(self, now: datetime) -> None:
        for key in tuple(self._tracked):
            if self._tracked[key].expires_at <= now:
                del self._tracked[key]
