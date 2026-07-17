from __future__ import annotations

import asyncio

import pytest
from nonebot.exception import MockApiException
from pytest import MonkeyPatch

from ironsbot.config.models.message import (
    OutboundRateLimitConfig,
    OutboundRateLimitWindowConfig,
)
from ironsbot.shared.messaging import outbound_rate_limit
from ironsbot.shared.messaging.outbound_rate_limit import (
    GroupOutboundRateLimitService,
    MultiWindowGroupRateLimiter,
    reset_outbound_rate_limit_state,
    use_preacquired_push_permit,
)
from tests.helpers.config import stub_app_config

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


def _set_config(
    monkeypatch: MonkeyPatch,
    *,
    windows: list[OutboundRateLimitWindowConfig] | None = None,
    queue_wait: float = 0.2,
    queue_size: int = 10,
) -> None:
    monkeypatch.setattr(
        outbound_rate_limit,
        "get_app_config",
        lambda: stub_app_config(
            outbound_rate_limit_config=OutboundRateLimitConfig(
                enabled=True,
                windows=windows or _windows((60.0, 10), (600.0, 30)),
                push_queue_max_wait_seconds=queue_wait,
                push_queue_max_messages=queue_size,
                cooldown_message="进入冷却",
            )
        ),
    )
    monkeypatch.setattr(
        GroupOutboundRateLimitService,
        "_is_limited_group",
        staticmethod(lambda group_id: group_id != ADMIN_GROUP_ID),
    )


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


def test_service_ignores_admin_groups_and_private_targets(
    monkeypatch: MonkeyPatch,
) -> None:
    _set_config(monkeypatch, windows=_windows((60.0, 1)))
    service = GroupOutboundRateLimitService()

    assert service.acquire_reply(None, now=0).allowed
    assert service.acquire_reply(None, now=1).allowed
    assert service.acquire_reply(ADMIN_GROUP_ID, now=0).allowed
    assert service.acquire_reply(ADMIN_GROUP_ID, now=1).allowed


def test_push_waits_for_capacity_without_blocking_other_groups(
    monkeypatch: MonkeyPatch,
) -> None:
    _set_config(
        monkeypatch,
        windows=_windows((0.03, 1)),
        queue_wait=0.2,
    )
    service = GroupOutboundRateLimitService()

    async def _run() -> None:
        first = await service.acquire_push(GROUP_ID, source="first")
        assert first.allowed

        waiting = asyncio.create_task(
            service.acquire_push(GROUP_ID, source="waiting")
        )
        await asyncio.sleep(0)
        other_group = await service.acquire_push(
            OTHER_GROUP_ID,
            source="other",
        )
        delayed = await waiting

        assert other_group.allowed
        assert delayed.allowed

    try:
        asyncio.run(_run())
    finally:
        service.reset()


def test_push_queue_rejects_when_full(
    monkeypatch: MonkeyPatch,
) -> None:
    _set_config(
        monkeypatch,
        windows=_windows((1.0, 1)),
        queue_wait=0.05,
        queue_size=1,
    )
    service = GroupOutboundRateLimitService()

    async def _run() -> None:
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
        asyncio.run(_run())
    finally:
        service.reset()


def test_api_hook_appends_boundary_notice_and_rolls_back_failure(
    monkeypatch: MonkeyPatch,
) -> None:
    _set_config(monkeypatch, windows=_windows((60.0, 1)))
    reset_outbound_rate_limit_state()

    async def _run() -> None:
        data: dict[str, object] = {
            "group_id": GROUP_ID,
            "message": "正文",
        }
        await outbound_rate_limit._check_group_send_api(
            None,  # type: ignore[arg-type]
            "send_group_msg",
            data,
        )
        assert str(data["message"]) == "正文\n\n进入冷却"

        await outbound_rate_limit._finalize_group_send_api(
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
            None,  # type: ignore[arg-type]
            "send_group_msg",
            retry_data,
        )
        assert str(retry_data["message"]) == "重试\n\n进入冷却"

    try:
        asyncio.run(_run())
    finally:
        reset_outbound_rate_limit_state()


def test_api_hook_suppresses_messages_after_group_limit(
    monkeypatch: MonkeyPatch,
) -> None:
    _set_config(monkeypatch, windows=_windows((60.0, 1)))
    reset_outbound_rate_limit_state()

    async def _run() -> None:
        first: dict[str, object] = {
            "group_id": GROUP_ID,
            "message": "first",
        }
        await outbound_rate_limit._check_group_send_api(
            None,  # type: ignore[arg-type]
            "send_group_msg",
            first,
        )
        await outbound_rate_limit._finalize_group_send_api(
            None,  # type: ignore[arg-type]
            None,
            "send_group_msg",
            first,
            {"message_id": 1},
        )

        blocked: dict[str, object] = {
            "group_id": GROUP_ID,
            "message": "blocked",
        }
        with pytest.raises(MockApiException):
            await outbound_rate_limit._check_group_send_api(
                None,  # type: ignore[arg-type]
                "send_group_msg",
                blocked,
            )

    try:
        asyncio.run(_run())
    finally:
        reset_outbound_rate_limit_state()


def test_preacquired_push_permit_is_not_counted_twice(
    monkeypatch: MonkeyPatch,
) -> None:
    _set_config(monkeypatch, windows=_windows((60.0, 1)))
    reset_outbound_rate_limit_state()

    async def _run() -> None:
        decision = await (
            outbound_rate_limit.group_outbound_rate_limit_service.acquire_push(
                GROUP_ID,
                source="test push",
            )
        )
        assert decision.permit is not None

        data: dict[str, object] = {
            "group_id": GROUP_ID,
            "message": "push",
        }
        with use_preacquired_push_permit(decision.permit):
            await outbound_rate_limit._check_group_send_api(
                None,  # type: ignore[arg-type]
                "send_group_msg",
                data,
            )
        await outbound_rate_limit._finalize_group_send_api(
            None,  # type: ignore[arg-type]
            None,
            "send_group_msg",
            data,
            {"message_id": 1},
        )

        with pytest.raises(MockApiException):
            await outbound_rate_limit._check_group_send_api(
                None,  # type: ignore[arg-type]
                "send_group_msg",
                {"group_id": GROUP_ID, "message": "blocked"},
            )

    try:
        asyncio.run(_run())
    finally:
        reset_outbound_rate_limit_state()
