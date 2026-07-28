from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from nonebot.exception import MockApiException
from nonebot.matcher import current_event

from ironsbot.config.models.messaging import (
    OutboundRateLimitConfig,
    OutboundRateLimitWindowConfig,
)
from ironsbot.core.features import FeatureConfig
from ironsbot.integrations.onebot import outbound as outbound_rate_limit
from ironsbot.integrations.onebot.outbound import (
    GroupOutboundRateLimitService,
    MultiWindowGroupRateLimiter,
    OutboundRateLimitDecision,
    use_preacquired_push_permit,
)
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from nonebot.adapters import Event

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
    ).delivery.outbound


def test_outbound_rate_limit_is_disabled_by_default() -> None:
    service = build_test_runtime().delivery.outbound

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
        waiting = asyncio.create_task(
            service.acquire_push(GROUP_ID, source="waiting")
        )
        await asyncio.sleep(0)
        other_group = await service.acquire_push(OTHER_GROUP_ID, source="other")
        delayed = await waiting

        assert other_group.allowed
        assert delayed.allowed

    try:
        asyncio.run(run())
    finally:
        service.reset()


def test_priority_queue_is_unbounded_and_prefers_superuser_replies() -> None:
    service = _service(windows=_windows((0.01, 1)))

    async def run() -> None:
        assert (await service.acquire_push(GROUP_ID, source="first")).allowed
        order: list[str] = []

        async def record(
            label: str,
            request: Awaitable[OutboundRateLimitDecision],
        ) -> OutboundRateLimitDecision:
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
        await asyncio.sleep(0)
        superuser_task = asyncio.create_task(
            record("superuser", service.acquire_superuser_reply(GROUP_ID))
        )

        results = await asyncio.gather(superuser_task, *push_tasks)

        assert all(result.allowed for result in results)
        assert order[0] == "superuser"

    try:
        asyncio.run(run())
    finally:
        service.reset()


def test_superuser_group_reply_uses_priority_queue() -> None:
    service = _service(
        windows=_windows((60.0, 1)),
        superuser_ids=(SUPERUSER_ID,),
    )

    async def run() -> None:
        first = service.acquire_reply(GROUP_ID)
        assert first.permit is not None

        data: dict[str, object] = {
            "group_id": GROUP_ID,
            "message": "superuser reply",
        }
        token = current_event.set(
            cast("Event", SimpleNamespace(user_id=SUPERUSER_ID))
        )
        try:
            queued = asyncio.create_task(
                outbound_rate_limit._check_group_send_api(
                    service,
                    None,  # type: ignore[arg-type]
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
        await outbound_rate_limit._finalize_group_send_api(
            service,
            None,  # type: ignore[arg-type]
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

    async def run() -> None:
        data: dict[str, object] = {"group_id": GROUP_ID, "message": "正文"}
        await outbound_rate_limit._check_group_send_api(
            service,
            None,  # type: ignore[arg-type]
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

        await outbound_rate_limit._finalize_group_send_api(
            service,
            None,  # type: ignore[arg-type]
            RuntimeError("send failed"),
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
        await outbound_rate_limit._check_group_send_api(
            service,
            None,  # type: ignore[arg-type]
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

    async def run() -> None:
        first: dict[str, object] = {"group_id": GROUP_ID, "message": "first"}
        await outbound_rate_limit._check_group_send_api(
            service,
            None,  # type: ignore[arg-type]
            "send_group_msg",
            first,
        )
        await outbound_rate_limit._finalize_group_send_api(
            service,
            None,  # type: ignore[arg-type]
            None,
            "send_group_msg",
            first,
            {"message_id": 1},
        )

        with pytest.raises(MockApiException):
            await outbound_rate_limit._check_group_send_api(
                service,
                None,  # type: ignore[arg-type]
                "send_group_msg",
                {"group_id": GROUP_ID, "message": "blocked"},
            )

    try:
        asyncio.run(run())
    finally:
        service.reset()


def test_preacquired_push_permit_is_not_counted_twice() -> None:
    service = _service(windows=_windows((60.0, 1)))

    async def run() -> None:
        decision = await service.acquire_push(GROUP_ID, source="test push")
        assert decision.permit is not None

        data: dict[str, object] = {"group_id": GROUP_ID, "message": "push"}
        with use_preacquired_push_permit(service, decision.permit):
            await outbound_rate_limit._check_group_send_api(
                service,
                None,  # type: ignore[arg-type]
                "send_group_msg",
                data,
            )
        await outbound_rate_limit._finalize_group_send_api(
            service,
            None,  # type: ignore[arg-type]
            None,
            "send_group_msg",
            data,
            {"message_id": 1},
        )

        with pytest.raises(MockApiException):
            await outbound_rate_limit._check_group_send_api(
                service,
                None,  # type: ignore[arg-type]
                "send_group_msg",
                {"group_id": GROUP_ID, "message": "blocked"},
            )

    try:
        asyncio.run(run())
    finally:
        service.reset()
