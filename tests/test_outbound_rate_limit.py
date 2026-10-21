from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import pytest
from nonebot.adapters.onebot.v11 import Bot
from nonebot.exception import MockApiException
from nonebot.matcher import current_event

from ironsbot.config.models.features import FeatureConfig
from ironsbot.config.models.messaging import (
    OutboundRateLimitConfig,
    OutboundRateLimitWindowConfig,
)
from ironsbot.core.outbound import SendResult
from ironsbot.integrations.onebot.outbound_hooks import OneBotOutboundRateLimitHooks
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

    from nonebot.adapters import Event

GROUP_ID = 100
OTHER_GROUP_ID = 101
ADMIN_GROUP_ID = 200
SUPERUSER_ID = 201
HOOK_BOT = Mock(spec=Bot)


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


def test_superuser_group_reply_uses_priority_queue() -> None:
    service = _service(
        windows=_windows((60.0, 1)),
        superuser_ids=(SUPERUSER_ID,),
    )
    hooks = OneBotOutboundRateLimitHooks(service)

    async def run() -> None:
        first = service.acquire_reply(GROUP_ID)
        assert first.permit is not None

        data: dict[str, object] = {
            "group_id": GROUP_ID,
            "message": "superuser reply",
        }
        token = current_event.set(cast("Event", SimpleNamespace(user_id=SUPERUSER_ID)))
        try:
            queued = asyncio.create_task(
                hooks.check(
                    HOOK_BOT,
                    "send_group_msg",
                    data,
                )
            )
            await asyncio.sleep(0)
        finally:
            current_event.reset(token)

        assert not queued.done()
        service.rollback(first.permit)
        await queued
        await hooks.finalize(
            HOOK_BOT,
            None,
            "send_group_msg",
            data,
            {"message_id": 1},
        )

    try:
        asyncio.run(run())
    finally:
        service.reset()


def test_api_failure_drops_pending_pushes_but_keeps_superuser_replies() -> None:
    service = _service(windows=_windows((60.0, 1)))
    hooks = OneBotOutboundRateLimitHooks(service)

    async def run() -> None:
        data: dict[str, object] = {"group_id": GROUP_ID, "message": "正文"}
        await hooks.check(
            HOOK_BOT,
            "send_group_msg",
            data,
        )
        assert str(data["message"]) == "正文\n\n进入冷却"

        waiting_push = asyncio.create_task(
            service.acquire_push(GROUP_ID, source="waiting")
        )
        waiting_superuser = asyncio.create_task(
            service.acquire_superuser_reply(GROUP_ID)
        )
        await asyncio.sleep(0)

        await hooks.finalize(
            HOOK_BOT,
            RuntimeError("账号状态为离线"),
            "send_group_msg",
            data,
            None,
        )
        dropped_push = await waiting_push
        assert not dropped_push.allowed
        assert dropped_push.reason == "queue_cleared"

        released_superuser = await waiting_superuser
        assert released_superuser.allowed
        service.rollback(released_superuser.permit)

        retry_data: dict[str, object] = {
            "group_id": GROUP_ID,
            "message": "重试",
        }
        await hooks.check(
            HOOK_BOT,
            "send_group_msg",
            retry_data,
        )
        assert str(retry_data["message"]) == "重试\n\n进入冷却"

    try:
        asyncio.run(run())
    finally:
        service.reset()


def test_api_hook_suppresses_messages_after_group_limit() -> None:
    service = _service(windows=_windows((60.0, 1)))
    hooks = OneBotOutboundRateLimitHooks(service)

    async def run() -> None:
        first: dict[str, object] = {"group_id": GROUP_ID, "message": "first"}
        await hooks.check(
            HOOK_BOT,
            "send_group_msg",
            first,
        )
        await hooks.finalize(
            HOOK_BOT,
            None,
            "send_group_msg",
            first,
            {"message_id": 1},
        )

        with pytest.raises(MockApiException):
            await hooks.check(
                HOOK_BOT,
                "send_group_msg",
                {"group_id": GROUP_ID, "message": "blocked"},
            )

    try:
        asyncio.run(run())
    finally:
        service.reset()


def test_managed_send_permit_is_not_counted_twice() -> None:
    service = _service(windows=_windows((60.0, 1)))
    hooks = OneBotOutboundRateLimitHooks(service)

    async def run() -> None:
        async def send(attempt: OutboundSendAttempt) -> SendResult:
            assert attempt.cooldown_notice == "进入冷却"
            data: dict[str, object] = {"group_id": GROUP_ID, "message": "push"}
            attempt.start()
            await hooks.check(
                HOOK_BOT,
                "send_group_msg",
                data,
            )
            await hooks.finalize(
                HOOK_BOT, None, "send_group_msg", data, {"message_id": 1}
            )
            return SendResult(delivered=True, message_id="1")

        assert (await service.execute_send(GROUP_ID, send, proactive=True)).delivered

        with pytest.raises(MockApiException):
            await hooks.check(
                HOOK_BOT,
                "send_group_msg",
                {"group_id": GROUP_ID, "message": "blocked"},
            )

    try:
        asyncio.run(run())
    finally:
        service.reset()


@pytest.mark.asyncio
async def test_uncertain_hook_failure_cannot_refund_reserved_capacity() -> None:
    service = _service(windows=_windows((60.0, 1)))
    hooks = OneBotOutboundRateLimitHooks(service)
    data: dict[str, object] = {"group_id": GROUP_ID, "message": "result"}
    await hooks.check(HOOK_BOT, "send_group_msg", data)
    await hooks.finalize(HOOK_BOT, TimeoutError(), "send_group_msg", data, None)
    assert not service.acquire_reply(GROUP_ID).allowed


@pytest.mark.asyncio
async def test_native_hook_does_not_consume_other_adapters_capacity() -> None:
    from nonebot.adapters import Bot as AdapterBot

    service = _service(windows=_windows((60.0, 1)))
    hooks = OneBotOutboundRateLimitHooks(service)
    data: dict[str, object] = {"group_id": GROUP_ID, "message": "other adapter"}
    bot = Mock(spec=AdapterBot)
    await hooks.check(bot, "send_group_msg", data)
    await hooks.finalize(
        bot, RuntimeError("not our protocol"), "send_group_msg", data, None
    )
    assert service.acquire_reply(GROUP_ID).allowed
