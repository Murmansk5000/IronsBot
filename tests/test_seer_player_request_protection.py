import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest

from ironsbot.services.operations.headless_pool import (
    HeadlessRequestPriority,
    current_headless_request_priority,
    current_headless_workflow,
)
from ironsbot.services.seer.player_request_protection import (
    PlayerRequestPausedError,
    PlayerRequestProtectionService,
)

ADMIN_ID = 90001
USER_ID = 10001


class _Features:
    def is_superuser(self, user_id: int) -> bool:
        return user_id == ADMIN_ID


class _Headless:
    def __init__(self) -> None:
        self.wait_calls: list[float] = []
        self.cancelled_background_errors: list[Exception] = []

    @property
    def healthy_worker_count(self) -> int:
        return 1

    def cancel_waiting_background(self, error: Exception) -> None:
        self.cancelled_background_errors.append(error)

    async def wait_until_available(self, *, timeout: float) -> object:
        self.wait_calls.append(timeout)
        return object()


def _config(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "enabled": True,
        "max_queued_queries": 3,
        "disconnect_pause_seconds": 60.0,
        "repeat_disconnect_window_seconds": 600.0,
        "repeat_disconnect_pause_seconds": 300.0,
        "superuser_priority": True,
        "superuser_bypass_pause": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _spawn(coroutine: Any, *, name: str) -> asyncio.Task[Any]:
    return asyncio.create_task(coroutine, name=name)


def _service(
    **config_overrides: object,
) -> tuple[PlayerRequestProtectionService, _Headless]:
    headless = _Headless()
    return (
        PlayerRequestProtectionService(
            cast("Any", _config(**config_overrides)),
            _Features(),
            cast("Any", headless),
            _spawn,
        ),
        headless,
    )


def test_workflows_can_progress_concurrently_before_packet_scheduling() -> None:
    async def run() -> None:
        service, _headless = _service()
        started = asyncio.Event()
        second_started = asyncio.Event()
        release = asyncio.Event()
        events: list[str] = []

        async def first() -> str:
            events.append("first-start")
            started.set()
            await release.wait()
            events.append("first-end")
            return "first"

        async def second() -> str:
            events.append("second")
            second_started.set()
            return "second"

        first_task = asyncio.create_task(
            service.run(first, user_id=USER_ID, label="first")
        )
        await started.wait()
        second_task = asyncio.create_task(
            service.run(second, user_id=USER_ID + 1, label="second")
        )
        await asyncio.wait_for(second_started.wait(), timeout=1.0)
        assert events == ["first-start", "second"]

        release.set()
        assert await first_task == "first"
        assert await second_task == "second"
        assert events == ["first-start", "second", "first-end"]

    asyncio.run(run())


def test_superuser_bypasses_normal_workflow_capacity() -> None:
    async def run() -> None:
        service, _headless = _service(max_queued_queries=1)
        started = asyncio.Event()
        release = asyncio.Event()
        events: list[str] = []

        async def active() -> str:
            started.set()
            await release.wait()
            events.append("active")
            return "active"

        async def normal() -> str:
            events.append("normal")
            return "normal"

        async def admin() -> str:
            events.append("admin")
            return "admin"

        active_task = asyncio.create_task(
            service.run(active, user_id=USER_ID, label="active")
        )
        await started.wait()
        normal_task = asyncio.create_task(
            service.run(normal, user_id=USER_ID + 1, label="normal")
        )
        await asyncio.sleep(0)
        admin_task = asyncio.create_task(
            service.run(admin, user_id=ADMIN_ID, label="admin")
        )

        assert await normal_task == "normal"
        assert await admin_task == "admin"

        release.set()
        assert await active_task == "active"
        assert events == ["normal", "admin", "active"]

    asyncio.run(run())


def test_priority_is_delegated_to_packet_scheduler_context() -> None:
    async def run() -> None:
        service, _headless = _service()
        started = asyncio.Event()
        release = asyncio.Event()
        events: list[str] = []

        async def active() -> str:
            events.append("active-start")
            started.set()
            await release.wait()
            events.append("active-end")
            return "active"

        async def background() -> str:
            events.append("background")
            return "background"

        async def interactive() -> str:
            events.append("interactive")
            return "interactive"

        active_task = asyncio.create_task(
            service.run(active, user_id=USER_ID, label="active")
        )
        await started.wait()
        background_task = asyncio.create_task(
            service.run(
                background,
                user_id=None,
                label="background",
                background=True,
            )
        )
        interactive_task = asyncio.create_task(
            service.run(interactive, user_id=USER_ID + 1, label="interactive")
        )
        await asyncio.sleep(0)

        release.set()
        assert await active_task == "active"
        assert await background_task == "background"
        assert await interactive_task == "interactive"
        assert events == [
            "active-start",
            "background",
            "interactive",
            "active-end",
        ]

    asyncio.run(run())


def test_background_request_timeout_releases_queue() -> None:
    async def run() -> None:
        service, _headless = _service()
        started = asyncio.Event()
        events: list[str] = []

        async def stuck_background() -> str:
            started.set()
            await asyncio.Event().wait()
            return "background"

        async def interactive() -> str:
            events.append("interactive")
            return "interactive"

        background_task = asyncio.create_task(
            service.run(
                stuck_background,
                user_id=None,
                label="background",
                background=True,
                timeout_seconds=0.01,
            )
        )
        await started.wait()
        interactive_task = asyncio.create_task(
            service.run(interactive, user_id=USER_ID, label="interactive")
        )

        with pytest.raises(asyncio.TimeoutError):
            await background_task
        assert await interactive_task == "interactive"
        assert events == ["interactive"]

    asyncio.run(run())


def test_disconnect_pauses_new_requests_and_cancels_background_work() -> None:
    async def run() -> None:
        service, _headless = _service()
        started = asyncio.Event()
        release = asyncio.Event()
        background_started = asyncio.Event()

        async def active() -> str:
            started.set()
            await release.wait()
            return "active"

        async def background() -> str:
            background_started.set()
            await asyncio.Event().wait()
            return "background"

        async def queued() -> str:
            return "queued"

        active_task = asyncio.create_task(
            service.run(active, user_id=USER_ID, label="active")
        )
        await started.wait()
        background_task = asyncio.create_task(
            service.run(
                background,
                user_id=None,
                label="background",
                background=True,
            )
        )
        await background_started.wait()

        await service.on_headless_state_change(
            previous=True,
            connected=False,
            reason="connection lost",
            source="test",
        )
        with pytest.raises(asyncio.CancelledError):
            await background_task
        with pytest.raises(PlayerRequestPausedError):
            await service.run(queued, user_id=USER_ID + 2, label="new")
        assert len(_headless.cancelled_background_errors) == 1

        release.set()
        assert await active_task == "active"

    asyncio.run(run())


def test_superuser_waits_for_reconnect_during_pause() -> None:
    async def run() -> None:
        service, headless = _service()
        await service.on_headless_state_change(
            previous=True,
            connected=False,
            reason="connection lost",
            source="test",
        )

        async def operation() -> str:
            return "done"

        assert (
            await service.run(operation, user_id=ADMIN_ID, label="admin")
            == "done"
        )
        assert headless.wait_calls == [60.0]

    asyncio.run(run())


def test_superuser_basic_and_detail_use_distinct_workflow_priorities() -> None:
    async def run() -> None:
        service, _headless = _service()

        async def priority() -> tuple[HeadlessRequestPriority, int]:
            workflow = current_headless_workflow()
            assert workflow is not None
            return current_headless_request_priority().priority, workflow.sequence

        admin_basic = await service.run(
            priority,
            user_id=ADMIN_ID,
            label="basic",
            priority=HeadlessRequestPriority.BASIC,
        )
        admin_detail = await service.run(
            priority,
            user_id=ADMIN_ID,
            label="detail",
        )
        normal_basic = await service.run(
            priority,
            user_id=USER_ID,
            label="normal-basic",
            priority=HeadlessRequestPriority.BASIC,
        )

        assert admin_basic == (HeadlessRequestPriority.SUPERUSER_BASIC, 0)
        assert admin_detail == (HeadlessRequestPriority.SUPERUSER_DETAIL, 1)
        assert normal_basic == (HeadlessRequestPriority.BASIC, 2)

    asyncio.run(run())
