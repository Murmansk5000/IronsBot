# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from math import ceil
from time import monotonic
from typing import TYPE_CHECKING, Any, NoReturn, Protocol, TypeVar, cast

from ironsbot.core.semantic_requests import SemanticRequest, semantic_request_scope

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.services.operations.headless_pool import HeadlessPool, HeadlessWorker

T = TypeVar("T")
logger = logging.getLogger(__name__)


class PlayerRequestBusyError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("player request queue is full")


class PlayerRequestPausedError(RuntimeError):
    def __init__(self, remaining_seconds: float) -> None:
        self.remaining_seconds = max(remaining_seconds, 0.0)
        super().__init__("player requests are paused")


class PlayerRequestReconnectError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("headless reconnect failed")


class SuperuserLookup(Protocol):
    def is_superuser(self, user_id: int) -> bool: ...


class PlayerRequestProtectionConfig(Protocol):
    enabled: bool
    max_queued_queries: int
    disconnect_pause_seconds: float
    repeat_disconnect_window_seconds: float
    repeat_disconnect_pause_seconds: float
    superuser_priority: bool
    superuser_bypass_pause: bool


@dataclass(slots=True)
class _QueuedRequest:
    label: str
    operation: Callable[[], Awaitable[Any]]
    future: asyncio.Future[Any]
    user_id: int | None
    bypass_pause: bool
    background: bool
    timeout_seconds: float | None
    semantic_request: SemanticRequest | None = None
    priority: bool = False


class PlayerRequestProtectionService:
    """Schedule live player workflows across independent headless connections."""

    def __init__(
        self,
        config: PlayerRequestProtectionConfig,
        features: SuperuserLookup,
        headless: HeadlessPool,
        spawn: TaskSpawner,
        *,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._config = config
        self._features = features
        self._headless = headless
        self._spawn = spawn
        self._now = now or monotonic
        self._priority: deque[_QueuedRequest] = deque()
        self._normal: deque[_QueuedRequest] = deque()
        self._background: deque[_QueuedRequest] = deque()
        self._active: dict[int, _QueuedRequest] = {}
        self._draining = False
        self._by_request_key: dict[tuple[str, str], _QueuedRequest] = {}
        self._pause_until = 0.0
        self._last_disconnect_at: float | None = None

    async def run(  # noqa: PLR0913
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        user_id: int | None,
        label: str,
        background: bool = False,
        timeout_seconds: float | None = None,
        semantic_request: SemanticRequest | None = None,
        _retry_after_background_failure: bool = True,
    ) -> T:
        if not self._config.enabled:
            with semantic_request_scope(semantic_request, user_id=user_id):
                return await operation()

        is_superuser = (
            user_id is not None and self._features.is_superuser(user_id)
        )
        bypass_pause = (
            is_superuser and self._config.superuser_bypass_pause
        )
        if self._paused() and not bypass_pause:
            raise PlayerRequestPausedError(self.pause_remaining_seconds())

        request_key = _semantic_request_key(semantic_request)
        if request_key and (existing := self._by_request_key.get(request_key)):
            if existing.future.done():
                self._by_request_key.pop(request_key, None)
            else:
                joined_background = existing.background
                if not background:
                    self._promote(
                        existing,
                        priority=(
                            is_superuser
                            and self._config.superuser_priority
                        ),
                    )
                try:
                    return cast("T", await existing.future)
                except Exception:
                    if (
                        joined_background
                        and not background
                        and _retry_after_background_failure
                    ):
                        return await self.run(
                            operation,
                            user_id=user_id,
                            label=label,
                            background=False,
                            timeout_seconds=timeout_seconds,
                            semantic_request=semantic_request,
                            _retry_after_background_failure=False,
                        )
                    raise

        item = _QueuedRequest(
            label=label,
            operation=cast("Callable[[], Awaitable[Any]]", operation),
            future=asyncio.get_running_loop().create_future(),
            user_id=user_id,
            bypass_pause=bypass_pause,
            background=background,
            timeout_seconds=timeout_seconds,
            semantic_request=semantic_request,
            priority=is_superuser and self._config.superuser_priority,
        )
        self._enqueue(item, priority=item.priority)
        if request_key:
            self._by_request_key[request_key] = item
        self._start_next()
        try:
            return cast("T", await item.future)
        except asyncio.CancelledError:
            item.future.cancel()
            raise

    async def on_headless_state_change(
        self,
        *,
        previous: bool | None,
        connected: bool,
        reason: str,
        source: str,
    ) -> None:
        if connected:
            self._start_next()
            return
        if previous is not True or not self._config.enabled:
            return
        if self._headless.has_connected_worker():
            return

        current = self._now()
        repeated = (
            self._last_disconnect_at is not None
            and current - self._last_disconnect_at
            <= self._config.repeat_disconnect_window_seconds
        )
        pause_seconds = (
            self._config.repeat_disconnect_pause_seconds
            if repeated
            else self._config.disconnect_pause_seconds
        )
        self._last_disconnect_at = current
        self._pause_until = max(self._pause_until, current + pause_seconds)
        self._reject_waiting(self._normal)
        self._reject_waiting(self._background)
        logger.warning(
            "player request circuit opened: pause=%.0fs repeated=%s "
            "source=%s reason=%s",
            pause_seconds,
            repeated,
            source,
            reason,
        )

    def pause_remaining_seconds(self) -> float:
        return max(self._pause_until - self._now(), 0.0)

    def _paused(self) -> bool:
        return self.pause_remaining_seconds() > 0

    def _enqueue(self, item: _QueuedRequest, *, priority: bool) -> None:
        if item.background:
            self._background.append(item)
            return

        waits_for_active_request = bool(self._active)
        if (
            waits_for_active_request
            and self._interactive_waiting_count()
            >= self._config.max_queued_queries
        ):
            if not priority:
                raise PlayerRequestBusyError
            if not self._normal:
                raise PlayerRequestBusyError
            displaced = self._normal.pop()
            self._release_request_key(displaced)
            self._reject(displaced, PlayerRequestBusyError())

        if priority:
            self._priority.append(item)
        else:
            self._normal.append(item)

    def _promote(self, item: _QueuedRequest, *, priority: bool) -> None:
        """Move a pending prefetch into the interactive priority class."""

        if item in self._active.values():
            return
        if not item.background and (item.priority or not priority):
            return
        for queue in (self._priority, self._normal, self._background):
            with suppress(ValueError):
                queue.remove(item)
        item.background = False
        item.priority = priority
        if priority:
            self._priority.append(item)
        else:
            self._normal.append(item)

    def _interactive_waiting_count(self) -> int:
        return sum(
            not item.future.cancelled()
            for item in (*self._priority, *self._normal)
        )

    def _start_next(self) -> None:
        if self._draining:
            return
        self._draining = True
        self._spawn(
            self._drain(),
            name="seer-player-request-dispatch",
        )

    async def _drain(self) -> None:
        try:
            while self._has_waiting_item():
                worker = self._headless.try_acquire()
                if worker is None:
                    return
                item = self._next_item()
                if item is None:
                    self._headless.release(worker)
                    return
                self._active[id(item)] = item
                self._spawn(
                    self._execute(item, worker),
                    name=f"seer-player-request:{worker.key}",
                )
        finally:
            self._draining = False

    def _has_waiting_item(self) -> bool:
        return any((self._priority, self._normal, self._background))

    def _next_item(self) -> _QueuedRequest | None:
        for queue in (self._priority, self._normal, self._background):
            while queue:
                item = queue.popleft()
                if not item.future.cancelled():
                    return item
        return None

    async def _execute(
        self,
        item: _QueuedRequest,
        worker: HeadlessWorker,
    ) -> None:
        try:
            if self._paused() and item.bypass_pause:
                await self._wait_for_reconnect()
            elif self._paused():
                self._raise_paused()
            with semantic_request_scope(
                item.semantic_request,
                user_id=item.user_id,
            ):
                result = await self._headless.run_on(
                    worker,
                    lambda: self._run_operation(item),
                )
        except asyncio.CancelledError:
            item.future.cancel()
            raise
        except asyncio.TimeoutError as error:
            logger.warning(
                "player request timed out: label=%s background=%s timeout=%.1fs",
                item.label,
                item.background,
                item.timeout_seconds or 0.0,
            )
            if not item.future.done():
                item.future.set_exception(error)
        except Exception as error:  # noqa: BLE001
            if not item.future.done():
                item.future.set_exception(error)
        else:
            if not item.future.done():
                item.future.set_result(result)
        finally:
            self._active.pop(id(item), None)
            self._release_request_key(item)
            self._start_next()

    async def _run_operation(self, item: _QueuedRequest) -> Any:
        if item.timeout_seconds is None:
            return await item.operation()

        async def execute_operation() -> Any:
            return await item.operation()

        operation_task = self._spawn(
            execute_operation(),
            name=f"seer-player-request-operation:{item.label}",
        )
        try:
            return await asyncio.wait_for(
                asyncio.shield(operation_task),
                timeout=item.timeout_seconds,
            )
        except (asyncio.CancelledError, asyncio.TimeoutError):
            operation_task.cancel()
            raise

    async def _wait_for_reconnect(self) -> None:
        try:
            await self._headless.wait_until_available(
                timeout=max(self._config.disconnect_pause_seconds, 1.0)
            )
        except Exception as error:
            raise PlayerRequestReconnectError from error

    def _raise_paused(self) -> NoReturn:
        raise PlayerRequestPausedError(self.pause_remaining_seconds())

    def _reject_waiting(self, queue: deque[_QueuedRequest]) -> None:
        while queue:
            item = queue.popleft()
            self._release_request_key(item)
            self._reject(
                item,
                PlayerRequestPausedError(self.pause_remaining_seconds()),
            )

    @staticmethod
    def _reject(item: _QueuedRequest, error: Exception) -> None:
        if not item.future.done():
            item.future.set_exception(error)

    def _release_request_key(self, item: _QueuedRequest) -> None:
        if (
            (request_key := _semantic_request_key(item.semantic_request)) is not None
            and self._by_request_key.get(request_key) is item
        ):
            self._by_request_key.pop(request_key, None)


def _semantic_request_key(
    request: SemanticRequest | None,
) -> tuple[str, str] | None:
    if request is None:
        return None
    return request.action.id, request.target.key


def player_request_protection_message(error: Exception) -> str:
    if isinstance(error, PlayerRequestBusyError):
        return "当前米米号查询较多，请稍后再试。"
    if isinstance(error, PlayerRequestPausedError):
        seconds = max(1, ceil(error.remaining_seconds))
        return f"无头米米号刚断线，查询暂缓约 {seconds} 秒，请稍后再试。"
    if isinstance(error, PlayerRequestReconnectError):
        return "无头米米号仍在自动重连，请稍后再试。"
    return "米米号查询暂时不可用，请稍后再试。"
