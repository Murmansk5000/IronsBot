# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from math import ceil
from time import monotonic
from typing import TYPE_CHECKING, Any, NoReturn, Protocol, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.services.operations.headless import HeadlessService

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
    bypass_pause: bool
    background: bool
    timeout_seconds: float | None


class PlayerRequestProtectionService:
    """Serialize live player workflows and retain a small priority queue."""

    def __init__(
        self,
        config: PlayerRequestProtectionConfig,
        features: SuperuserLookup,
        headless: HeadlessService,
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
        self._active: _QueuedRequest | None = None
        self._pause_until = 0.0
        self._last_disconnect_at: float | None = None

    async def run(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        user_id: int | None,
        label: str,
        background: bool = False,
        timeout_seconds: float | None = None,
    ) -> T:
        if not self._config.enabled:
            return await operation()

        is_superuser = (
            user_id is not None and self._features.is_superuser(user_id)
        )
        bypass_pause = (
            is_superuser and self._config.superuser_bypass_pause
        )
        if self._paused() and not bypass_pause:
            raise PlayerRequestPausedError(self.pause_remaining_seconds())

        item = _QueuedRequest(
            label=label,
            operation=cast("Callable[[], Awaitable[Any]]", operation),
            future=asyncio.get_running_loop().create_future(),
            bypass_pause=bypass_pause,
            background=background,
            timeout_seconds=timeout_seconds,
        )
        self._enqueue(
            item,
            priority=is_superuser and self._config.superuser_priority,
        )
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
        if connected or previous is not True or not self._config.enabled:
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

        waits_for_active_request = self._active is not None
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
            self._reject(displaced, PlayerRequestBusyError())

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
        if self._active is not None:
            return
        next_item = self._next_item()
        if next_item is None:
            return
        self._active = next_item
        self._spawn(
            self._execute(next_item),
            name="seer-player-request",
        )

    def _next_item(self) -> _QueuedRequest | None:
        for queue in (self._priority, self._normal, self._background):
            while queue:
                item = queue.popleft()
                if not item.future.cancelled():
                    return item
        return None

    async def _execute(self, item: _QueuedRequest) -> None:
        try:
            if self._paused() and item.bypass_pause:
                await self._wait_for_reconnect()
            elif self._paused():
                self._raise_paused()
            result = await self._run_operation(item)
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
            self._active = None
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
            self._reject(
                item,
                PlayerRequestPausedError(self.pause_remaining_seconds()),
            )

    @staticmethod
    def _reject(item: _QueuedRequest, error: Exception) -> None:
        if not item.future.done():
            item.future.set_exception(error)


def player_request_protection_message(error: Exception) -> str:
    if isinstance(error, PlayerRequestBusyError):
        return "当前米米号查询较多，请稍后再试。"
    if isinstance(error, PlayerRequestPausedError):
        seconds = max(1, ceil(error.remaining_seconds))
        return f"无头米米号刚断线，查询暂缓约 {seconds} 秒，请稍后再试。"
    if isinstance(error, PlayerRequestReconnectError):
        return "无头米米号仍在自动重连，请稍后再试。"
    return "米米号查询暂时不可用，请稍后再试。"
