from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from ironsbot.config.models.features import FeatureConfig
from ironsbot.config.models.messaging import (
    OutboundRateLimitConfig,
    OutboundRateLimitWindowConfig,
)
from ironsbot.core.outbound import DeliveryFailureKind, SendResult
from ironsbot.core.platform import ActorRef, Platform
from ironsbot.services.messaging import outbound_limits
from ironsbot.services.messaging.outbound_limits import (
    GroupOutboundRateLimitService,
    MultiWindowGroupRateLimiter,
    OutboundRateLimitDecision,
    OutboundSendAttempt,
)
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from collections.abc import Awaitable


GROUP_ID = 100
OTHER_GROUP_ID = 101
ADMIN_GROUP_ID = 200
SUPERUSER_ID = 201


def _windows(
    *items: tuple[float, int],
) -> list[OutboundRateLimitWindowConfig]:
    return [
        OutboundRateLimitWindowConfig(
            window_seconds=window_seconds,
            max_messages=max_messages,
        )
        for window_seconds, max_messages in items
    ]


def _service(
    *,
    windows: list[OutboundRateLimitWindowConfig] | None = None,
    superuser_ids: tuple[int, ...] = (),
) -> GroupOutboundRateLimitService:
    config = OutboundRateLimitConfig(
        enabled=True,
        windows=windows or _windows((60.0, 10), (600.0, 30)),
        cooldown_message="进入冷却",
    )
    return build_test_runtime(
        outbound_config=config,
        superuser_ids=superuser_ids,
        feature_config=FeatureConfig(
            group_policy={str(ADMIN_GROUP_ID): ["admin_notice"]},
        ),
    ).outbound


def test_outbound_rate_limit_is_disabled_by_default() -> None:
    service = build_test_runtime().outbound

    assert service.acquire_reply(GROUP_ID, now=0).allowed
    assert service.acquire_reply(GROUP_ID, now=1).allowed


def test_multi_window_rate_limit_checks_and_records_atomically() -> None:
    limiter = MultiWindowGroupRateLimiter()
    windows = _windows((10.0, 2), (100.0, 3))

    first = limiter.acquire(GROUP_ID, windows, source="reply", now=0)
    second = limiter.acquire(GROUP_ID, windows, source="reply", now=1)
    blocked_by_short_window = limiter.acquire(
        GROUP_ID,
        windows,
        source="reply",
        now=2,
    )
    third = limiter.acquire(GROUP_ID, windows, source="reply", now=11)
    blocked_by_long_window = limiter.acquire(
        GROUP_ID,
        windows,
        source="reply",
        now=12,
    )

    assert first.allowed
    assert second.allowed
    assert second.permit is not None
    assert second.permit.append_cooldown_notice
    assert not blocked_by_short_window.allowed
    assert blocked_by_short_window.retry_after_seconds == pytest.approx(8.0)
    assert third.allowed
    assert third.permit is not None
    assert third.permit.append_cooldown_notice
    assert not blocked_by_long_window.allowed
    assert blocked_by_long_window.retry_after_seconds == pytest.approx(88.0)


def test_rejected_message_does_not_pollute_other_window() -> None:
    limiter = MultiWindowGroupRateLimiter()
    windows = _windows((10.0, 1), (100.0, 2))

    assert limiter.acquire(GROUP_ID, windows, source="reply", now=0).allowed
    assert not limiter.acquire(GROUP_ID, windows, source="reply", now=1).allowed
    second_recorded = limiter.acquire(
        GROUP_ID,
        windows,
        source="reply",
        now=10.1,
    )

    assert second_recorded.allowed
    assert second_recorded.permit is not None
    assert second_recorded.permit.append_cooldown_notice


def test_outbound_permit_can_be_rolled_back() -> None:
    limiter = MultiWindowGroupRateLimiter()
    windows = _windows((60.0, 1))
    first = limiter.acquire(GROUP_ID, windows, source="reply", now=0)
    assert first.permit is not None

    assert limiter.rollback(first.permit)
    assert limiter.acquire(GROUP_ID, windows, source="reply", now=1).allowed


def test_service_ignores_admin_groups_and_private_targets() -> None:
    service = _service(windows=_windows((60.0, 1)))

    assert service.acquire_reply(None, now=0).allowed
    assert service.acquire_reply(None, now=1).allowed
    assert service.acquire_reply(ADMIN_GROUP_ID, now=0).allowed
    assert service.acquire_reply(ADMIN_GROUP_ID, now=1).allowed


def test_push_waits_for_capacity_without_blocking_other_groups() -> None:
    service = _service(windows=_windows((0.03, 1)))

    async def run() -> None:
        assert (await service.acquire_push(GROUP_ID, source="first")).allowed
        waiting = asyncio.create_task(service.acquire_push(GROUP_ID, source="waiting"))
        await asyncio.sleep(0)
        other_group = await service.acquire_push(OTHER_GROUP_ID, source="other")
        delayed = await waiting

        assert other_group.allowed
        assert delayed.allowed

    try:
        asyncio.run(run())
    finally:
        service.reset()


@pytest.mark.parametrize("expire_before_pushes", [False, True])
def test_priority_queue_is_unbounded_and_prefers_superuser_replies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    expire_before_pushes: bool,
) -> None:
    clock = [0.0]
    # Freeze only the limiter clock, not asyncio's clock or timeout handling.
    monkeypatch.setattr(
        outbound_limits, "time", SimpleNamespace(monotonic=lambda: clock[0])
    )
    service = _service(windows=_windows((0.1, 1)))

    async def run() -> None:
        reserved = await service.acquire_push(GROUP_ID, source="first")
        assert reserved.allowed
        if expire_before_pushes:
            clock[0] = 1.0
        order: list[str] = []
        started: asyncio.Queue[str] = asyncio.Queue()

        async def record(
            label: str,
            request: Awaitable[OutboundRateLimitDecision],
        ) -> OutboundRateLimitDecision:
            started.put_nowait(label)
            result = await request
            order.append(label)
            return result

        push_tasks = [
            asyncio.create_task(
                record(
                    f"push-{index}",
                    service.acquire_push(GROUP_ID, source=f"push-{index}"),
                )
            )
            for index in range(12)
        ]
        for index in range(len(push_tasks)):
            assert await started.get() == f"push-{index}"
        if expire_before_pushes:
            reserved = await push_tasks[0]
        superuser_task = asyncio.create_task(
            record("superuser", service.acquire_superuser_reply(GROUP_ID))
        )
        assert await started.get() == "superuser"
        assert not superuser_task.done()
        assert order == (["push-0"] if expire_before_pushes else [])

        # All remaining requests are queued before capacity becomes available.
        service.rollback(reserved.permit)
        superuser_result = await superuser_task
        service.rollback(superuser_result.permit)
        for task in push_tasks[int(expire_before_pushes) :]:
            result = await task
            service.rollback(result.permit)

        results = await asyncio.gather(superuser_task, *push_tasks)

        assert all(result.allowed for result in results)
        expected = [f"push-{index}" for index in range(len(push_tasks))]
        expected.insert(int(expire_before_pushes), "superuser")
        assert order == expected

    try:
        asyncio.run(asyncio.wait_for(run(), timeout=5))
    finally:
        service.reset()


@pytest.mark.asyncio
async def test_superuser_send_uses_explicit_actor_and_priority_queue() -> None:
    service = _service(windows=_windows((60.0, 1)), superuser_ids=(SUPERUSER_ID,))
    reserved = service.acquire_reply(GROUP_ID)
    calls: list[str | None] = []

    async def send(attempt: OutboundSendAttempt) -> SendResult:
        calls.append(attempt.cooldown_notice)
        attempt.start()
        return SendResult(delivered=True, message_id="1")

    waiting = asyncio.create_task(
        service.execute_send(
            GROUP_ID, send, actor=ActorRef(Platform.ONEBOT, str(SUPERUSER_ID))
        )
    )
    try:
        await asyncio.sleep(0)
        assert not waiting.done()
        assert not calls
        service.rollback(reserved.permit)
        assert (await asyncio.wait_for(waiting, timeout=1)).delivered
        assert calls == ["进入冷却"]
    finally:
        service.reset()
        await asyncio.gather(waiting, return_exceptions=True)


@pytest.mark.asyncio
async def test_transport_failure_clears_push_queue_not_operator_queue() -> None:
    service = _service(windows=_windows((60.0, 1)))
    pending: list[asyncio.Task[OutboundRateLimitDecision]] = []

    async def offline(attempt: OutboundSendAttempt) -> SendResult:
        assert attempt.cooldown_notice == "进入冷却"
        pending.extend(
            (
                asyncio.create_task(service.acquire_push(GROUP_ID, source="waiting")),
                asyncio.create_task(service.acquire_superuser_reply(GROUP_ID)),
            )
        )
        await asyncio.sleep(0)
        attempt.start()
        attempt.interrupted = True
        return SendResult(
            delivered=False,
            error_code="offline",
            failure_kind=DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
        )

    try:
        assert not (await service.execute_send(GROUP_ID, offline)).delivered
        dropped, operator = await asyncio.wait_for(asyncio.gather(*pending), timeout=1)
        assert not dropped.allowed
        assert dropped.reason == "queue_cleared"
        assert operator.allowed
        service.rollback(operator.permit)

        async def retry(attempt: OutboundSendAttempt) -> SendResult:
            assert attempt.cooldown_notice == "进入冷却"
            attempt.start()
            return SendResult(delivered=True, message_id="retry")

        assert (await service.execute_send(GROUP_ID, retry)).delivered
    finally:
        service.reset()
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", [GROUP_ID, None])
async def test_explicit_sender_enforces_group_window_without_api_hooks(
    group_id: int | None,
) -> None:
    service = _service(windows=_windows((60.0, 1)))
    notices: list[str | None] = []

    async def send(attempt: OutboundSendAttempt) -> SendResult:
        notices.append(attempt.cooldown_notice)
        attempt.start()
        return SendResult(delivered=True, message_id="1")

    assert (await service.execute_send(group_id, send)).delivered
    second = await service.execute_send(group_id, send)
    if group_id is None:
        assert second.delivered
        assert notices == [None, None]
    else:
        assert not second.delivered
        assert not second.attempted
        assert second.error_code == "rate_limit"
        assert notices == ["进入冷却"]
