from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from ironsbot.integrations.qq_official import reply_sequences
from ironsbot.integrations.qq_official.reply_sequences import (
    QQOfficialReplySequenceAllocator,
)

if TYPE_CHECKING:
    import pytest


def test_reply_sequences_are_unique_under_concurrency() -> None:
    allocator = QQOfficialReplySequenceAllocator(limit=64)

    with ThreadPoolExecutor(max_workers=8) as pool:
        allocations = tuple(pool.map(allocator.allocate, ["event-id"] * 64))

    assert sorted(item.sequence for item in allocations if item.sequence) == list(
        range(1, 65)
    )


def test_expired_reply_window_does_not_reopen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [10.0]
    monkeypatch.setattr(reply_sequences, "monotonic", lambda: now[0])
    allocator = QQOfficialReplySequenceAllocator(ttl_seconds=5)

    assert allocator.allocate("event-id").sequence == 1
    now[0] = 16.0

    assert allocator.allocate("event-id").reason == "expired"
    assert allocator.allocate("event-id").reason == "expired"


def test_reply_sequence_tracking_is_bounded() -> None:
    allocator = QQOfficialReplySequenceAllocator(max_tracked_messages=2)

    allocator.allocate("oldest")
    allocator.allocate("newer")
    allocator.allocate("newest")

    assert allocator.allocate("oldest").sequence == 1
