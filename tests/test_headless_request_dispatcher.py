from __future__ import annotations

import asyncio
from collections import Counter
from typing import TYPE_CHECKING, Any

import pytest

from ironsbot.services.operations.headless_activity import HeadlessOperationTracker
from ironsbot.services.operations.headless_errors import DisconnectedError
from ironsbot.services.operations.headless_pool import (
    HeadlessRequestDispatcher,
    HeadlessRequestPriority,
    HeadlessRequestPriorityState,
    HeadlessWorkerSlot,
    HeadlessWorkflowState,
    PooledHeadlessGame,
    headless_request_priority_scope,
    headless_workflow_scope,
)
from ironsbot.services.operations.request_feedback import request_feedback_scope

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
async def test_background_fills_workers_then_yields_to_queued_foreground(
    worker_count: int,
) -> None:
    game, events, _started = _pool(worker_count)
    release = asyncio.Event()
    expected_background = worker_count

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
    assert all(label != "basic" for _worker, label in events)

    release.set()
    await asyncio.gather(*background_tasks, basic_task)
    assert events[expected_background][1] == "basic"


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_count", [1, 2, 3, 4])
async def test_background_work_is_evenly_distributed_across_workers(
    worker_count: int,
) -> None:
    game, events, _started = _pool(worker_count)

    async def background(index: int) -> None:
        with headless_request_priority_scope(HeadlessRequestPriority.BACKGROUND):
            await game.step(f"background-{index}")

    await asyncio.gather(*(background(index) for index in range(12)))

    assignments = Counter(worker_id for worker_id, _label in events)
    assert len(assignments) == worker_count
    assert max(assignments.values()) - min(assignments.values()) <= 1


@pytest.mark.asyncio
async def test_failed_packet_retries_on_another_healthy_worker() -> None:
    game, events, _started = _pool(2, failing_workers=frozenset((0,)))

    result = await game.step("retry")

    assert result == f"{SECOND_WORKER_ID}:retry"
    assert events == [(10000, "retry"), (SECOND_WORKER_ID, "retry")]
    assert game.user_id == SECOND_WORKER_ID


@pytest.mark.asyncio
async def test_request_feedback_reflects_actual_worker_dispatch_state() -> None:
    game, _events, started = _pool(1)
    release = asyncio.Event()
    feedback: list[tuple[str, bool]] = []

    async def send_feedback(label: str, *, queued: bool) -> None:
        feedback.append((label, queued))

    with request_feedback_scope("first", send_feedback):
        first = asyncio.create_task(game.step("first", release))
    await started.setdefault("first", asyncio.Event()).wait()

    with request_feedback_scope("second", send_feedback):
        second = asyncio.create_task(game.step("second"))
    await asyncio.sleep(0)

    assert feedback == [("first", False), ("second", True)]
    release.set()
    await asyncio.gather(first, second)


@pytest.mark.asyncio
async def test_request_feedback_is_sent_only_for_the_first_packet() -> None:
    game, _events, _started = _pool(1)
    feedback: list[tuple[str, bool]] = []

    async def send_feedback(label: str, *, queued: bool) -> None:
        feedback.append((label, queued))

    with request_feedback_scope("workflow", send_feedback):
        await game.step("first")
        await game.step("second")

    assert feedback == [("workflow", False)]


@pytest.mark.asyncio
async def test_earlier_workflow_resumes_before_backfilled_workflow() -> None:
    game, events, started = _pool(1)
    release = asyncio.Event()
    first_workflow = HeadlessWorkflowState(
        sequence=1,
        label="first",
        user_id=1,
        priority_state=HeadlessRequestPriorityState(
            HeadlessRequestPriority.INTERACTIVE
        ),
    )
    later_workflow = HeadlessWorkflowState(
        sequence=2,
        label="later",
        user_id=2,
        priority_state=HeadlessRequestPriorityState(
            HeadlessRequestPriority.INTERACTIVE
        ),
    )

    async def first() -> None:
        with (
            headless_workflow_scope(first_workflow),
            headless_request_priority_scope(
                HeadlessRequestPriority.INTERACTIVE,
                state=first_workflow.priority_state,
            ),
        ):
            await game.step("first-1", release)
            await game.step("first-2")

    async def later() -> None:
        with (
            headless_workflow_scope(later_workflow),
            headless_request_priority_scope(
                HeadlessRequestPriority.INTERACTIVE,
                state=later_workflow.priority_state,
            ),
        ):
            await game.step("later")

    first_task = asyncio.create_task(first())
    await started.setdefault("first-1", asyncio.Event()).wait()
    later_task = asyncio.create_task(later())
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first_task, later_task)

    assert [label for _worker, label in events] == [
        "first-1",
        "first-2",
        "later",
    ]


@pytest.mark.asyncio
async def test_idle_worker_backfills_a_later_workflow() -> None:
    game, events, started = _pool(2)
    release = asyncio.Event()
    first_workflow = HeadlessWorkflowState(
        sequence=1,
        label="first",
        user_id=1,
        priority_state=HeadlessRequestPriorityState(
            HeadlessRequestPriority.INTERACTIVE
        ),
    )
    later_workflow = HeadlessWorkflowState(
        sequence=2,
        label="later",
        user_id=2,
        priority_state=HeadlessRequestPriorityState(
            HeadlessRequestPriority.INTERACTIVE
        ),
    )

    async def submit(
        workflow: HeadlessWorkflowState,
        label: str,
        wait: asyncio.Event | None,
    ) -> None:
        with (
            headless_workflow_scope(workflow),
            headless_request_priority_scope(
                HeadlessRequestPriority.INTERACTIVE,
                state=workflow.priority_state,
            ),
        ):
            await game.step(label, wait)

    first_task = asyncio.create_task(submit(first_workflow, "first", release))
    await started.setdefault("first", asyncio.Event()).wait()
    later_task = asyncio.create_task(submit(later_workflow, "later", release))
    await started.setdefault("later", asyncio.Event()).wait()
    release.set()
    await asyncio.gather(first_task, later_task)

    assert {label for _worker, label in events} == {"first", "later"}


@pytest.mark.asyncio
async def test_ready_packets_follow_the_five_player_workflow_priorities() -> None:
    game, events, started = _pool(1)
    release = asyncio.Event()

    async def held_background() -> None:
        with headless_request_priority_scope(HeadlessRequestPriority.BACKGROUND):
            await game.step("held", release)

    async def queued(
        label: str,
        priority: HeadlessRequestPriority,
        sequence: int,
    ) -> None:
        state = HeadlessRequestPriorityState(priority)
        workflow = HeadlessWorkflowState(
            sequence=sequence,
            label=label,
            user_id=sequence,
            priority_state=state,
        )
        with (
            headless_workflow_scope(workflow),
            headless_request_priority_scope(priority, state=state),
        ):
            await game.step(label)

    held_task = asyncio.create_task(held_background())
    await started.setdefault("held", asyncio.Event()).wait()
    tasks = [
        asyncio.create_task(
            queued("interactive", HeadlessRequestPriority.INTERACTIVE, 0)
        ),
        asyncio.create_task(queued("basic", HeadlessRequestPriority.BASIC, 1)),
        asyncio.create_task(
            queued("super-detail", HeadlessRequestPriority.SUPERUSER_DETAIL, 2)
        ),
        asyncio.create_task(
            queued("super-basic", HeadlessRequestPriority.SUPERUSER_BASIC, 3)
        ),
    ]
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(held_task, *tasks)

    assert [label for _worker, label in events] == [
        "held",
        "super-basic",
        "super-detail",
        "basic",
        "interactive",
    ]
