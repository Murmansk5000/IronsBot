from __future__ import annotations

import asyncio

import pytest
from nonebot.exception import MockApiException

from ironsbot.config.models.messaging import (
    OutboundRateLimitConfig,
    OutboundRateLimitWindowConfig,
)
from ironsbot.core.features import FeatureConfig
from ironsbot.integrations.onebot import outbound as outbound_rate_limit
from ironsbot.integrations.onebot.outbound import (
    GroupOutboundRateLimitService,
    MultiWindowGroupRateLimiter,
    use_preacquired_push_permit,
)
from tests.helpers.runtime import build_test_runtime

GROUP_ID = 100
OTHER_GROUP_ID = 101
ADMIN_GROUP_ID = 200


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
    queue_wait: float = 0.2,
    queue_size: int = 10,
) -> GroupOutboundRateLimitService:
    config = OutboundRateLimitConfig(
        enabled=True,
        windows=windows or _windows((60.0, 10), (600.0, 30)),
        push_queue_max_wait_seconds=queue_wait,
        push_queue_max_messages=queue_size,
        cooldown_message="进入冷却",
    )
    return build_test_runtime(
        outbound_config=config,
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
    service = _service(windows=_windows((0.03, 1)), queue_wait=0.2)

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


def test_push_queue_rejects_when_full() -> None:
    service = _service(
        windows=_windows((1.0, 1)),
        queue_wait=0.05,
        queue_size=1,
    )

    async def run() -> None:
        assert (await service.acquire_push(GROUP_ID, source="first")).allowed
        waiting = asyncio.create_task(
            service.acquire_push(GROUP_ID, source="waiting")
        )
        await asyncio.sleep(0)

        rejected = await service.acquire_push(GROUP_ID, source="overflow")
        timed_out = await waiting

        assert not rejected.allowed
        assert rejected.reason == "queue_full"
        assert not timed_out.allowed
        assert timed_out.reason == "queue_timeout"

    try:
        asyncio.run(run())
    finally:
        service.reset()


def test_api_hook_appends_boundary_notice_and_rolls_back_failure() -> None:
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

        await outbound_rate_limit._finalize_group_send_api(
            service,
            None,  # type: ignore[arg-type]
            RuntimeError("send failed"),
            "send_group_msg",
            data,
            None,
        )
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
