from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from ironsbot.integrations.qq_official.reply_sequences import (
    QQOfficialReplySequenceAllocator,
    ReplySequenceKey,
)

NOW = datetime(2026, 9, 15, tzinfo=UTC)
DEADLINE = NOW + timedelta(minutes=5)
KEY = ReplySequenceKey("group", "group-openid", "event-id")
REPLY_LIMIT = 4
SECOND_SEQUENCE = 2


def _allocator(*, capacity: int = 10_000) -> QQOfficialReplySequenceAllocator:
    return QQOfficialReplySequenceAllocator(
        max_tracked_messages=capacity,
        clock=lambda: NOW,
    )


def test_reply_sequences_are_unique_under_concurrency() -> None:
    allocator = _allocator()

    def allocate(_index: int):
        return allocator.allocate(KEY, expires_at=DEADLINE, limit=64)

    with ThreadPoolExecutor(max_workers=8) as pool:
        allocations = tuple(pool.map(allocate, range(64)))

    assert sorted(item.sequence for item in allocations if item.sequence) == list(
        range(1, 65)
    )


def test_expired_reply_window_is_rejected_from_event_deadline() -> None:
    allocator = _allocator()

    rejected = allocator.allocate(
        KEY,
        expires_at=NOW - timedelta(seconds=1),
        limit=REPLY_LIMIT,
    )

    assert rejected.reason == "expired"


def test_live_reply_keys_are_not_evicted_at_capacity() -> None:
    allocator = _allocator(capacity=2)

    allocator.allocate(KEY, expires_at=DEADLINE, limit=REPLY_LIMIT)
    allocator.allocate(
        ReplySequenceKey("group", "other", "event-id"),
        expires_at=DEADLINE,
        limit=REPLY_LIMIT,
    )
    rejected = allocator.allocate(
        ReplySequenceKey("private", "actor", "event-id"),
        expires_at=DEADLINE,
        limit=REPLY_LIMIT,
    )

    assert rejected.reason == "capacity_exceeded"
    assert (
        allocator.allocate(KEY, expires_at=DEADLINE, limit=REPLY_LIMIT).sequence
        == SECOND_SEQUENCE
    )


def test_reply_sequence_allocation_reserves_consecutive_slots() -> None:
    allocator = _allocator()

    assert (
        allocator.allocate(
            KEY,
            expires_at=DEADLINE,
            limit=REPLY_LIMIT,
            count=3,
        ).sequence
        == 1
    )
    assert (
        allocator.allocate(KEY, expires_at=DEADLINE, limit=REPLY_LIMIT).sequence
        == REPLY_LIMIT
    )
    rejected = allocator.allocate(KEY, expires_at=DEADLINE, limit=REPLY_LIMIT)

    assert rejected.reason == "limit_exceeded"


def test_reply_sequence_reservation_is_atomic_when_limit_would_be_exceeded() -> None:
    allocator = _allocator()

    assert (
        allocator.allocate(
            KEY,
            expires_at=DEADLINE,
            limit=REPLY_LIMIT,
            count=3,
        ).sequence
        == 1
    )
    assert (
        allocator.allocate(
            KEY,
            expires_at=DEADLINE,
            limit=REPLY_LIMIT,
            count=2,
        ).reason
        == "limit_exceeded"
    )
    assert (
        allocator.allocate(KEY, expires_at=DEADLINE, limit=REPLY_LIMIT).sequence
        == REPLY_LIMIT
    )


def test_same_message_id_is_isolated_by_conversation() -> None:
    allocator = _allocator()
    other = ReplySequenceKey("group", "other-group", KEY.message_id)

    assert allocator.allocate(KEY, expires_at=DEADLINE, limit=5).sequence == 1
    assert allocator.allocate(other, expires_at=DEADLINE, limit=5).sequence == 1
