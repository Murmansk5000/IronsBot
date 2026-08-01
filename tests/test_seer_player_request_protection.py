import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest

from ironsbot.services.seer.player_request_protection import (
    PlayerRequestBusyError,
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
        self.connected = True
        self._workers = [SimpleNamespace(key="primary", busy=False)]

    def try_acquire(self) -> SimpleNamespace | None:
        for worker in self._workers:
            if not worker.busy:
                worker.busy = True
                return worker
        return None

    def release(self, worker: SimpleNamespace) -> None:
        worker.busy = False

    async def run_on(
        self,
        worker: SimpleNamespace,
        operation: Any,
    ) -> object:
        try:
            return await operation()
        finally:
            self.release(worker)

    def has_connected_worker(self) -> bool:
        return self.connected

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


def test_requests_run_one_at_a_time_in_arrival_order() -> None:
    async def run() -> None:
        service, _headless = _service()
        started = asyncio.Event()
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
            return "second"

        first_task = asyncio.create_task(
            service.run(first, user_id=USER_ID, label="first")
        )
        await started.wait()
        second_task = asyncio.create_task(
            service.run(second, user_id=USER_ID + 1, label="second")
        )
        await asyncio.sleep(0)
        assert events == ["first-start"]

        release.set()
        assert await first_task == "first"
        assert await second_task == "second"
        assert events == ["first-start", "first-end", "second"]

    asyncio.run(run())


def test_requests_use_all_available_headless_workers() -> None:
    async def run() -> None:
        service, headless = _service()
        headless._workers.append(SimpleNamespace(key="rank_a", busy=False))
        first_started = asyncio.Event()
        second_started = asyncio.Event()
        release = asyncio.Event()

        async def first() -> str:
            first_started.set()
            await release.wait()
            return "first"

        async def second() -> str:
            second_started.set()
            await release.wait()
            return "second"

        first_task = asyncio.create_task(
            service.run(first, user_id=USER_ID, label="first")
        )
        second_task = asyncio.create_task(
            service.run(second, user_id=USER_ID + 1, label="second")
        )
        await asyncio.wait_for(
            asyncio.gather(first_started.wait(), second_started.wait()),
            timeout=0.2,
        )
        release.set()
        assert await first_task == "first"
        assert await second_task == "second"

    asyncio.run(run())


def test_superuser_displaces_last_normal_request_when_queue_is_full() -> None:
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

        with pytest.raises(PlayerRequestBusyError):
            await normal_task

        release.set()
        assert await active_task == "active"
        assert await admin_task == "admin"
        assert events == ["active", "admin"]

    asyncio.run(run())


def test_interactive_request_runs_before_waiting_background_refresh() -> None:
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
        assert await interactive_task == "interactive"
        assert await background_task == "background"
        assert events == ["active-start", "active-end", "interactive", "background"]

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


def test_disconnect_pauses_normal_requests_and_clears_waiting_work() -> None:
    async def run() -> None:
        service, headless = _service()
        started = asyncio.Event()
        release = asyncio.Event()

        async def active() -> str:
            started.set()
            await release.wait()
            return "active"

        async def queued() -> str:
            raise AssertionError

        active_task = asyncio.create_task(
            service.run(active, user_id=USER_ID, label="active")
        )
        await started.wait()
        queued_task = asyncio.create_task(
            service.run(queued, user_id=USER_ID + 1, label="queued")
        )
        await asyncio.sleep(0)

        headless.connected = False
        await service.on_headless_state_change(
            previous=True,
            connected=False,
            reason="connection lost",
            source="test",
        )
        with pytest.raises(PlayerRequestPausedError):
            await queued_task
        with pytest.raises(PlayerRequestPausedError):
            await service.run(queued, user_id=USER_ID + 2, label="new")

        release.set()
        assert await active_task == "active"

    asyncio.run(run())


def test_superuser_waits_for_reconnect_during_pause() -> None:
    async def run() -> None:
        service, headless = _service()
        headless.connected = False
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
