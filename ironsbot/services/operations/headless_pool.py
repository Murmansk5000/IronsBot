# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
from collections import deque
from contextlib import contextmanager, suppress
from contextvars import Context, ContextVar, copy_context
from dataclasses import dataclass, field
from enum import IntEnum
from time import monotonic
from typing import TYPE_CHECKING, Any, NoReturn, Protocol, TypeVar, cast

from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator

    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.services.operations.headless_activity import (
        HeadlessOperationTracker,
    )

T = TypeVar("T")
logger = logging.getLogger(__name__)
MAX_PACKET_ATTEMPTS = 2


class HeadlessRequestPriority(IntEnum):
    SUPERUSER = 0
    BASIC = 10
    INTERACTIVE = 20
    BACKGROUND = 30


@dataclass(slots=True)
class HeadlessRequestPriorityState:
    priority: HeadlessRequestPriority

    def promote(self, priority: HeadlessRequestPriority) -> None:
        self.priority = min(self.priority, priority)


_request_priority: ContextVar[HeadlessRequestPriorityState | None] = ContextVar(
    "headless_request_priority",
    default=None,
)
_last_worker_user_id: ContextVar[int | None] = ContextVar(
    "headless_last_worker_user_id",
    default=None,
)


@contextmanager
def headless_request_priority_scope(
    priority: HeadlessRequestPriority,
    *,
    state: HeadlessRequestPriorityState | None = None,
) -> Iterator[HeadlessRequestPriorityState]:
    current = state or HeadlessRequestPriorityState(priority)
    current.promote(priority)
    token = _request_priority.set(current)
    try:
        yield current
    finally:
        _request_priority.reset(token)


def current_headless_request_priority() -> HeadlessRequestPriorityState:
    current = _request_priority.get()
    return current or HeadlessRequestPriorityState(
        HeadlessRequestPriority.INTERACTIVE
    )


class HeadlessPoolClient(Protocol):
    def get_client(self) -> Any: ...


@dataclass(slots=True)
class HeadlessWorkerSlot:
    name: str
    user_id: int
    client: HeadlessPoolClient
    active: bool = False
    assignments: int = 0
    available_since: float = field(default_factory=monotonic)

    def game(self) -> Any | None:
        try:
            return self.client.get_client()
        except (DisconnectedError, NotLoggedInError):
            return None


@dataclass(slots=True)
class _PacketRequest:
    sequence: int
    label: str
    operation: Callable[[Any], Awaitable[Any]]
    future: asyncio.Future[_PacketOutcome]
    priority_state: HeadlessRequestPriorityState
    context: Context
    queued_at: float
    excluded_workers: set[str] = field(default_factory=set)
    active_worker: str | None = None
    attempts: int = 0


@dataclass(frozen=True, slots=True)
class _PacketOutcome:
    worker_user_id: int | None
    result: Any = None
    error: BaseException | None = None


class HeadlessRequestDispatcher:
    """Schedule independent read packets across interchangeable clients."""

    def __init__(
        self,
        workers: list[HeadlessWorkerSlot],
        spawn: TaskSpawner,
    ) -> None:
        self._workers = workers
        self._spawn = spawn
        self._pending: deque[_PacketRequest] = deque()
        self._sequence = 0
        self._active_background = 0

    @property
    def healthy_worker_count(self) -> int:
        return sum(worker.game() is not None for worker in self._workers)

    @property
    def configured_worker_count(self) -> int:
        return len(self._workers)

    @property
    def primary_user_id(self) -> int:
        healthy = next(
            (worker for worker in self._workers if worker.game() is not None),
            None,
        )
        worker = healthy or (self._workers[0] if self._workers else None)
        if worker is None:
            message = "Headless Seer worker pool is empty"
            raise NotLoggedInError(message)
        return worker.user_id

    async def submit(
        self,
        operation: Callable[[Any], Awaitable[T]],
        *,
        label: str,
    ) -> T:
        loop = asyncio.get_running_loop()
        request = _PacketRequest(
            sequence=self._sequence,
            label=label,
            operation=cast("Callable[[Any], Awaitable[Any]]", operation),
            future=loop.create_future(),
            priority_state=current_headless_request_priority(),
            context=copy_context(),
            queued_at=monotonic(),
        )
        self._sequence += 1
        self._pending.append(request)
        self.dispatch()
        try:
            outcome = await asyncio.shield(request.future)
        except asyncio.CancelledError:
            if request.active_worker is None:
                with suppress(ValueError):
                    self._pending.remove(request)
                request.future.cancel()
            raise
        if outcome.worker_user_id is not None:
            _last_worker_user_id.set(outcome.worker_user_id)
        if outcome.error is not None:
            raise outcome.error
        return cast("T", outcome.result)

    def dispatch(self) -> None:
        while True:
            request = self._next_request()
            if request is None:
                return
            worker = self._next_idle_worker(request)
            if worker is None:
                self._pending.appendleft(request)
                return
            worker.active = True
            worker.assignments += 1
            request.active_worker = worker.name
            request.attempts += 1
            priority = request.priority_state.priority
            if priority is HeadlessRequestPriority.BACKGROUND:
                self._active_background += 1
            wait_seconds = monotonic() - request.queued_at
            logger.info(
                "headless packet scheduled: label=%s priority=%s worker=%s "
                "queue_wait=%.3fs attempt=%s",
                request.label,
                priority.name.lower(),
                worker.name,
                wait_seconds,
                request.attempts,
            )
            coroutine = self._execute(worker, request, priority)
            request.context.run(
                self._spawn,
                coroutine,
                name=f"headless-packet:{worker.name}:{request.label}",
            )

    def cancel_waiting_background(self, error: Exception) -> None:
        retained: deque[_PacketRequest] = deque()
        while self._pending:
            request = self._pending.popleft()
            if (
                request.priority_state.priority
                is HeadlessRequestPriority.BACKGROUND
            ):
                if not request.future.done():
                    request.future.set_result(
                        _PacketOutcome(worker_user_id=None, error=error)
                    )
                continue
            retained.append(request)
        self._pending = retained

    def _next_idle_worker(
        self,
        request: _PacketRequest,
    ) -> HeadlessWorkerSlot | None:
        candidates = [
            worker
            for worker in self._workers
            if not worker.active
            and worker.name not in request.excluded_workers
            and worker.game() is not None
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda item: (
                item.assignments,
                item.available_since,
                item.name,
            ),
        )

    def _next_request(self) -> _PacketRequest | None:
        healthy_count = self.healthy_worker_count
        if healthy_count <= 0:
            return None
        background_limit = max(1, healthy_count - 1)
        candidates = [
            item
            for item in self._pending
            if not item.future.cancelled()
            and (
                item.priority_state.priority
                is not HeadlessRequestPriority.BACKGROUND
                or self._active_background < background_limit
            )
            and self._has_worker_for(item)
        ]
        if not candidates:
            return None
        selected = min(
            candidates,
            key=lambda item: (item.priority_state.priority, item.sequence),
        )
        self._pending.remove(selected)
        return selected

    def _has_worker_for(self, request: _PacketRequest) -> bool:
        return any(
            worker.name not in request.excluded_workers
            and not worker.active
            and worker.game() is not None
            for worker in self._workers
        )

    async def _execute(  # noqa: C901 - retry and task completion are coupled
        self,
        worker: HeadlessWorkerSlot,
        request: _PacketRequest,
        started_priority: HeadlessRequestPriority,
    ) -> None:
        retry = False
        try:
            game = worker.game()
            if game is None:
                self._raise_worker_disconnected()
            result = await request.operation(game)
        except asyncio.CancelledError:
            raise
        except (DisconnectedError, NotLoggedInError) as error:
            request.excluded_workers.add(worker.name)
            retry = (
                request.attempts < MAX_PACKET_ATTEMPTS
                and self._has_healthy_alternative(request)
            )
            if not retry and not request.future.done():
                request.future.set_result(
                    _PacketOutcome(worker_user_id=worker.user_id, error=error)
                )
        except Exception as error:  # noqa: BLE001
            if not request.future.done():
                request.future.set_result(
                    _PacketOutcome(worker_user_id=worker.user_id, error=error)
                )
        else:
            if not request.future.done():
                request.future.set_result(
                    _PacketOutcome(
                        worker_user_id=worker.user_id,
                        result=result,
                    )
                )
        finally:
            worker.active = False
            worker.available_since = monotonic()
            request.active_worker = None
            if started_priority is HeadlessRequestPriority.BACKGROUND:
                self._active_background = max(0, self._active_background - 1)
            if retry and not request.future.done():
                request.queued_at = monotonic()
                self._pending.appendleft(request)
            self.dispatch()

    def _has_healthy_alternative(self, request: _PacketRequest) -> bool:
        return any(
            worker.name not in request.excluded_workers
            and worker.game() is not None
            for worker in self._workers
        )

    @staticmethod
    def _raise_worker_disconnected() -> NoReturn:
        message = "Headless Seer worker is disconnected"
        raise DisconnectedError(message)


class PooledHeadlessGame:
    """Duck-typed Seer game whose read calls are dispatched per packet."""

    def __init__(
        self,
        dispatcher: HeadlessRequestDispatcher,
        operations: HeadlessOperationTracker,
    ) -> None:
        self._dispatcher = dispatcher
        self.operations = operations

    @property
    def is_logged_in(self) -> bool:
        return self._dispatcher.healthy_worker_count > 0

    @property
    def user_id(self) -> int:
        return _last_worker_user_id.get() or self._dispatcher.primary_user_id

    async def send_and_wait(
        self,
        command_id: Any,
        *body: object,
        timeout: float | None = None,
    ) -> Any:
        async def invoke(game: Any) -> Any:
            return await game.send_and_wait(command_id, *body, timeout=timeout)

        return await self._dispatcher.submit(
            invoke,
            label=f"packet-{int(command_id)}",
        )

    async def get_user_info(self, user_id: int) -> Any:
        return await self._invoke("get_user_info", user_id)

    async def get_more_user_info(self, user_id: int) -> Any:
        return await self._invoke("get_more_user_info", user_id)

    async def get_user_online_info(self, user_id: int) -> Any:
        return await self._invoke("get_user_online_info", user_id)

    async def get_team_info(self, team_id: int) -> Any:
        return await self._invoke("get_team_info", team_id)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        async def pooled_method(*args: object, **kwargs: object) -> Any:
            return await self._invoke(name, *args, **kwargs)

        return pooled_method

    async def _invoke(
        self,
        method_name: str,
        *args: object,
        **kwargs: object,
    ) -> Any:
        async def invoke(game: Any) -> Any:
            method = getattr(game, method_name)
            return await method(*args, **kwargs)

        return await self._dispatcher.submit(invoke, label=method_name)
