from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from ironsbot.services.operations.headless_activity import HeadlessOperationTracker
from ironsbot.services.operations.headless_errors import DisconnectedError
from ironsbot.services.operations.headless_pool import (
    HeadlessRequestDispatcher,
    HeadlessRequestPriority,
    HeadlessWorkerSlot,
    PooledHeadlessGame,
    headless_request_priority_scope,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine

SECOND_WORKER_ID = 10001


def _spawn(
    coroutine: Coroutine[Any, Any, Any],
    *,
    name: str,
) -> asyncio.Task[Any]:
    return asyncio.create_task(coroutine, name=name)


class _Game:
    def __init__(
        self,
        user_id: int,
        events: list[tuple[int, str]],
        started: dict[str, asyncio.Event],
        *,
        fail: bool = False,
    ) -> None:
        self.user_id = user_id
        self._events = events
        self._started = started
        self._fail = fail

    async def step(
        self,
        label: str,
        release: asyncio.Event | None = None,
    ) -> str:
        self._events.append((self.user_id, label))
        self._started.setdefault(label, asyncio.Event()).set()
        if self._fail:
            msg = f"worker {self.user_id} disconnected"
            raise DisconnectedError(msg)
        if release is not None:
            await release.wait()
        return f"{self.user_id}:{label}"


class _Client:
    def __init__(self, game: _Game) -> None:
        self._game = game

    def get_client(self) -> _Game:
        return self._game


def _pool(
    count: int,
    *,
    failing_workers: frozenset[int] = frozenset(),
) -> tuple[PooledHeadlessGame, list[tuple[int, str]], dict[str, asyncio.Event]]:
    events: list[tuple[int, str]] = []
    started: dict[str, asyncio.Event] = {}
    workers = [
        HeadlessWorkerSlot(
            name=f"worker-{index}",
            user_id=10000 + index,
            client=_Client(
                _Game(
                    10000 + index,
                    events,
                    started,
                    fail=index in failing_workers,
                )
            ),
        )
        for index in range(count)
    ]
    dispatcher = HeadlessRequestDispatcher(workers, _spawn)
    return PooledHeadlessGame(
        dispatcher,
        HeadlessOperationTracker(),
    ), events, started


async def _wait_for_event_count(
    events: list[tuple[int, str]],
    count: int,
) -> None:
    for _ in range(1000):
        if len(events) >= count:
            return
        await asyncio.sleep(0)
    message = f"timed out waiting for {count} packet events"
    raise AssertionError(message)


@pytest.mark.asyncio
async def test_single_worker_yields_after_each_background_packet() -> None:
    game, events, started = _pool(1)
    release = asyncio.Event()

    async def background() -> None:
        with headless_request_priority_scope(HeadlessRequestPriority.BACKGROUND):
            await game.step("background-1", release)
            await game.step("background-2")

    async def basic() -> None:
        with headless_request_priority_scope(HeadlessRequestPriority.BASIC):
            await game.step("basic")

    background_task = asyncio.create_task(background())
    await started.setdefault("background-1", asyncio.Event()).wait()
    basic_task = asyncio.create_task(basic())
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(background_task, basic_task)

    assert [label for _worker, label in events] == [
        "background-1",
        "basic",
        "background-2",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_count", [1, 2, 3, 4])
async def test_background_parallelism_reserves_foreground_capacity(
    worker_count: int,
) -> None:
    game, events, _started = _pool(worker_count)
    release = asyncio.Event()
    expected_background = max(1, worker_count - 1)

    async def background(index: int) -> None:
        with headless_request_priority_scope(HeadlessRequestPriority.BACKGROUND):
            await game.step(f"background-{index}", release)

    async def basic() -> None:
        with headless_request_priority_scope(HeadlessRequestPriority.BASIC):
            await game.step("basic")

    background_tasks = [
        asyncio.create_task(background(index))
        for index in range(worker_count + 1)
    ]
    await _wait_for_event_count(events, expected_background)
    assert len(events) == expected_background

    basic_task = asyncio.create_task(basic())
    await asyncio.sleep(0)
    if worker_count == 1:
        assert all(label != "basic" for _worker, label in events)
    else:
        await _wait_for_event_count(events, expected_background + 1)
        assert events[-1][1] == "basic"

    release.set()
    await asyncio.gather(*background_tasks, basic_task)
    if worker_count == 1:
        assert events[1][1] == "basic"


@pytest.mark.asyncio
async def test_failed_packet_retries_on_another_healthy_worker() -> None:
    game, events, _started = _pool(2, failing_workers=frozenset((0,)))

    result = await game.step("retry")

    assert result == f"{SECOND_WORKER_ID}:retry"
    assert events == [(10000, "retry"), (SECOND_WORKER_ID, "retry")]
    assert game.user_id == SECOND_WORKER_ID
