from __future__ import annotations

import asyncio
import subprocess
import sys
from typing import TYPE_CHECKING, Any, TypeVar

import pytest

from ironsbot.config.models.messaging import (
    OutboundRateLimitConfig,
    OutboundRateLimitWindowConfig,
)
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.outbound import DeliveryFailureKind, SendResult
from ironsbot.services.messaging.outbound_limits import (
    GroupOutboundRateLimitService,
    OutboundSendAttempt,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine

T = TypeVar("T")


def _spawn(coroutine: Coroutine[Any, Any, T], *, name: str) -> asyncio.Task[T]:
    return asyncio.create_task(coroutine, name=name)


def _service() -> GroupOutboundRateLimitService:
    return GroupOutboundRateLimitService(
        OutboundRateLimitConfig(
            enabled=True,
            windows=[OutboundRateLimitWindowConfig(window_seconds=60, max_messages=1)],
        ),
        FeatureService({}, {}, frozenset()),
        _spawn,
    )


def test_late_failed_send_cannot_refund_a_new_permit_after_reset() -> None:
    service = _service()
    old = service.acquire_reply(100, now=0)
    assert old.permit is not None
    service.reset()
    fresh = service.acquire_reply(100, now=1)
    assert fresh.allowed
    service.settle_send(
        old.permit, SendResult(delivered=False, attempted=False, error_code="not_sent")
    )
    assert not service.acquire_reply(100, now=2).allowed


@pytest.mark.asyncio
async def test_nested_send_attempts_settle_each_group_independently() -> None:
    service = _service()

    async def inner(attempt: OutboundSendAttempt) -> SendResult:
        assert not attempt.started
        attempt.start()
        return SendResult(delivered=True, message_id="2")

    async def outer(attempt: OutboundSendAttempt) -> SendResult:
        assert not attempt.started
        assert (await service.execute_send(101, inner)).delivered
        assert not service.acquire_reply(100).allowed
        assert not service.acquire_reply(101).allowed
        attempt.start()
        return SendResult(delivered=True, message_id="1")

    assert (await service.execute_send(100, outer)).delivered
    assert not service.acquire_reply(100).allowed
    assert not service.acquire_reply(101).allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("started", [False, True])
@pytest.mark.parametrize("error", [asyncio.CancelledError, RuntimeError])
async def test_explicit_send_interruption_preserves_only_started_attempts(
    *, started: bool, error: type[BaseException]
) -> None:
    service = _service()

    async def send(attempt: OutboundSendAttempt) -> SendResult:
        if started:
            attempt.start()
        raise error()

    with pytest.raises(error):
        await service.execute_send(100, send)
    assert service.acquire_reply(100).allowed is not started


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,attempted,released",
    [
        (None, True, False),
        (DeliveryFailureKind.UNCERTAIN, True, False),
        (DeliveryFailureKind.UNCERTAIN, False, True),
        (DeliveryFailureKind.TRANSPORT_UNAVAILABLE, True, True),
        (DeliveryFailureKind.RETRYABLE, True, True),
        (DeliveryFailureKind.PERMANENT, True, True),
    ],
)
async def test_explicit_send_settles_from_receipt_not_exception_truthiness(
    kind: DeliveryFailureKind | None, *, attempted: bool, released: bool
) -> None:
    service = _service()
    expected = SendResult(
        delivered=False, error_code="test", attempted=attempted, failure_kind=kind
    )

    async def send(attempt: OutboundSendAttempt) -> SendResult:
        if attempted:
            attempt.start()
        return expected

    assert await service.execute_send(100, send) is expected
    assert service.acquire_reply(100).allowed is released


def test_conflicting_duplicate_receipt_cannot_refund_uncertain_delivery() -> None:
    service = _service()
    decision = service.acquire_reply(100, now=0)
    service.settle_send(
        decision.permit,
        SendResult(
            delivered=False,
            error_code="timeout",
            failure_kind=DeliveryFailureKind.UNCERTAIN,
        ),
    )
    service.settle_send(
        decision.permit,
        SendResult(delivered=False, error_code="late", attempted=False),
    )
    assert not service.acquire_reply(100, now=1).allowed


@pytest.mark.asyncio
async def test_cancelled_queue_waiter_leaves_capacity_for_fresh_work() -> None:
    service = _service()
    first = await service.acquire_push(100, source="first")
    waiting = asyncio.create_task(service.acquire_push(100, source="cancelled"))
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    service.rollback(first.permit)
    assert (await service.acquire_push(100, source="fresh")).allowed
    service.reset()


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_started", [False, True])
async def test_owner_cancellation_releases_waiters_without_restarting_worker(
    *, worker_started: bool
) -> None:
    workers: list[asyncio.Task[Any]] = []

    def spawn(coroutine: Coroutine[Any, Any, T], *, name: str) -> asyncio.Task[T]:
        task = asyncio.create_task(coroutine, name=name)
        workers.append(task)
        return task

    source = _service()
    service = GroupOutboundRateLimitService(source.config, source.features, spawn)
    await service.acquire_push(100, source="first")
    waiting = asyncio.create_task(service.acquire_push(100, source="waiting"))
    try:
        await asyncio.sleep(0)
        if worker_started:
            await asyncio.sleep(0)
        workers[0].cancel()
        await asyncio.gather(workers[0], return_exceptions=True)
        await asyncio.sleep(0)
        assert waiting.done()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert len(workers) == 1
    finally:
        service.reset()
        waiting.cancel()
        await asyncio.gather(waiting, *workers, return_exceptions=True)


def test_limits_import_and_execute_without_nonebot() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys, asyncio
sys.modules['nonebot'] = None
from ironsbot.config.models.messaging import OutboundRateLimitConfig
from ironsbot.core.feature_policy import FeatureService
from ironsbot.services.messaging.outbound_limits import GroupOutboundRateLimitService
service = GroupOutboundRateLimitService(
    OutboundRateLimitConfig(), FeatureService({}, {}, frozenset()), asyncio.create_task
)
assert asyncio.run(service.acquire_send(100)).allowed
service.reset()
""",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
