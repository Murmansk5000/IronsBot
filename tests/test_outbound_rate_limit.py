from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest
from ironsbot.config.models.message import (
    OutboundRateLimitConfig,
    OutboundRateLimitWindowConfig,
)
from ironsbot.shared.messaging.outbound_rate_limit import (
    GroupOutboundRateLimitService,
    MultiWindowGroupRateLimiter,
    reset_outbound_rate_limit_state,
    use_preacquired_push_permit,
)
from ironsbot.shared.messaging.targets import MessageTarget
from nonebot.adapters.onebot.v11 import Adapter, Bot
from nonebot.exception import MockApiException
from pytest import MonkeyPatch
from tests.helpers.config import stub_app_config

from ironsbot.shared.messaging import outbound_rate_limit, senders

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


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def _rate_limit_test_bot(
    monkeypatch: MonkeyPatch,
    call: Callable[..., Awaitable[Any]] | None = None,
) -> Bot:
    async def unexpected_api(_bot: Bot, _api: str, **_data: Any) -> Any:
        raise AssertionError

    adapter = Adapter.__new__(Adapter)
    monkeypatch.setattr(adapter, "_call_api", unexpected_api if call is None else call)
    return Bot(adapter, self_id="101")


@pytest.mark.parametrize(
    "phase", ["success", "reject", "cancel_calling", "cancel_transport"]
)
def test_real_bot_dispatch_and_cancel_boundary(
    monkeypatch: MonkeyPatch, phase: str
) -> None:
    _set_config(monkeypatch, windows=_windows((60.0, 1)))
    outbound_rate_limit.reset_outbound_rate_limit_state()

    async def run() -> None:
        entered = []
        finalized = []
        owner = None

        async def adapter_call(_bot: Any, api: Any, **_data: Any) -> Any:
            entered.append(api)
            if phase == "cancel_transport":
                raise asyncio.CancelledError
            return {"message_id": 1}

        bot = _rate_limit_test_bot(monkeypatch, adapter_call)

        async def calling(bot: Any, api: Any, data: Any) -> Any:
            await outbound_rate_limit._check_group_send_api(bot, api, data)
            if phase == "reject":
                raise MockApiException(
                    outbound_rate_limit._suppressed_result(
                        group_id=GROUP_ID, reason="synthetic known rejection"
                    )
                )
            if phase == "cancel_calling":
                assert owner is not None
                owner.cancel()

        async def called(bot: Any, error: Any, api: Any, data: Any, result: Any) -> Any:
            finalized.append(error)
            await outbound_rate_limit._finalize_group_send_api(
                bot, error, api, data, result
            )

        monkeypatch.setattr(bot, "_calling_api_hook", {calling})
        monkeypatch.setattr(bot, "_called_api_hook", {called})
        owner = asyncio.create_task(
            senders._send_target_message(
                MessageTarget("group", GROUP_ID),
                "synthetic boundary",
                index=0,
                bot=bot,
                interval_seconds=0,
            )
        )
        if phase.startswith("cancel"):
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(owner, timeout=2)
            assert not finalized
            assert (
                not outbound_rate_limit.group_outbound_rate_limit_service.acquire_reply(
                    GROUP_ID
                ).allowed
            )
        else:
            assert await asyncio.wait_for(owner, timeout=2) is (phase == "success")
            assert len(finalized) == 1
            assert outbound_rate_limit.group_outbound_rate_limit_service.acquire_reply(
                GROUP_ID
            ).allowed is (phase == "reject")
        assert len(entered) == (0 if phase in {"reject", "cancel_calling"} else 1)
        assert not outbound_rate_limit._api_permits
        assert outbound_rate_limit._preacquired_push_permit.get() is None
        assert owner.done()

    try:
        asyncio.run(run())
    finally:
        outbound_rate_limit.reset_outbound_rate_limit_state()


def test_queued_unsent_cancellation_keeps_capacity(monkeypatch: MonkeyPatch) -> None:
    _set_config(monkeypatch, windows=_windows((60.0, 1)), queue_wait=1)
    outbound_rate_limit.reset_outbound_rate_limit_state()

    async def run() -> None:
        service = outbound_rate_limit.group_outbound_rate_limit_service
        first = await service.acquire_push(
            GROUP_ID, source="synthetic occupying request"
        )
        assert first.permit is not None
        pending = asyncio.create_task(
            service.acquire_push(GROUP_ID, source="synthetic unsent waiter")
        )
        await asyncio.sleep(0)
        assert not pending.done()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        service.rollback(first.permit)
        await asyncio.sleep(0)
        fresh = service.acquire_reply(GROUP_ID)
        assert fresh.allowed
        assert not outbound_rate_limit._api_permits
        assert pending.done()

    try:
        asyncio.run(run())
    finally:
        outbound_rate_limit.reset_outbound_rate_limit_state()


def test_normal_exit_retains_deferred_error_finalization(
    monkeypatch: MonkeyPatch,
) -> None:
    _set_config(monkeypatch, windows=_windows((60.0, 1)))
    outbound_rate_limit.reset_outbound_rate_limit_state()

    async def run() -> None:
        service = outbound_rate_limit.group_outbound_rate_limit_service
        decision = await service.acquire_push(
            GROUP_ID, source="synthetic deferred hook"
        )
        data = {"group_id": GROUP_ID, "message": "synthetic deferred result"}
        with outbound_rate_limit.use_preacquired_push_permit(decision.permit):
            await outbound_rate_limit._check_group_send_api(
                _rate_limit_test_bot(monkeypatch), "send_group_msg", data
            )
        assert id(data) in outbound_rate_limit._api_permits
        await outbound_rate_limit._finalize_group_send_api(
            _rate_limit_test_bot(monkeypatch),
            OSError("synthetic error"),
            "send_group_msg",
            data,
            None,
        )
        assert not outbound_rate_limit._api_permits
        assert service.acquire_reply(GROUP_ID).allowed

    try:
        asyncio.run(run())
    finally:
        outbound_rate_limit.reset_outbound_rate_limit_state()


def test_cancel_cleanup_does_not_steal_equal_foreign_permit(
    monkeypatch: MonkeyPatch,
) -> None:
    _set_config(monkeypatch, windows=_windows((60.0, 1)))
    outbound_rate_limit.reset_outbound_rate_limit_state()

    async def run() -> None:
        decision = (
            await outbound_rate_limit.group_outbound_rate_limit_service.acquire_push(
                GROUP_ID, source="synthetic own scope"
            )
        )
        assert decision.permit is not None
        foreign = replace(decision.permit)
        assert foreign == decision.permit and foreign is not decision.permit
        foreign_key = -1
        outbound_rate_limit._api_permits[foreign_key] = foreign
        data = {"group_id": GROUP_ID, "message": "synthetic own API"}
        with (
            pytest.raises(asyncio.CancelledError),
            outbound_rate_limit.use_preacquired_push_permit(decision.permit),
        ):
            await outbound_rate_limit._check_group_send_api(
                _rate_limit_test_bot(monkeypatch), "send_group_msg", data
            )
            raise asyncio.CancelledError
        assert id(data) not in outbound_rate_limit._api_permits
        assert outbound_rate_limit._api_permits[foreign_key] is foreign
        assert len(outbound_rate_limit._api_permits) == 1

    try:
        asyncio.run(run())
    finally:
        outbound_rate_limit.reset_outbound_rate_limit_state()


def test_formal_registered_callback_accepts_arbitrary_results(
    monkeypatch: MonkeyPatch,
) -> None:
    _set_config(monkeypatch, windows=_windows((60.0, 50)))
    outbound_rate_limit.reset_outbound_rate_limit_state()
    assert "_calling_api_hook" not in Bot.__dict__
    assert "_called_api_hook" not in Bot.__dict__
    monkeypatch.setattr(outbound_rate_limit.Bot, "_calling_api_hook", set())
    monkeypatch.setattr(outbound_rate_limit.Bot, "_called_api_hook", set())
    monkeypatch.setattr(outbound_rate_limit, "_hooks_registered", False)
    assert Bot._calling_api_hook is outbound_rate_limit.Bot._calling_api_hook
    assert Bot._called_api_hook is outbound_rate_limit.Bot._called_api_hook
    outbound_rate_limit.setup_outbound_rate_limit_runtime()
    assert outbound_rate_limit._check_group_send_api in Bot._calling_api_hook
    assert outbound_rate_limit._finalize_group_send_api in Bot._called_api_hook
    results = [None, "synthetic", [1], {"synthetic": True}, object()]

    async def run() -> None:
        current = None

        async def call(_bot: Any, _api: Any, **_data: Any) -> Any:
            return current

        bot = _rate_limit_test_bot(monkeypatch, call)
        for value in results:
            current = value
            returned = await bot.send_group_msg(
                group_id=GROUP_ID, message="synthetic registered callback"
            )
            assert returned is value
            assert not outbound_rate_limit._api_permits

    try:
        asyncio.run(run())
    finally:
        outbound_rate_limit.reset_outbound_rate_limit_state()
