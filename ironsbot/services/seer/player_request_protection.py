# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from math import ceil
from time import monotonic
from typing import TYPE_CHECKING, Any, NoReturn, Protocol, TypeVar, cast

from ironsbot.core.semantic_requests import SemanticRequest, semantic_request_scope
from ironsbot.services.operations.headless_pool import (
    HeadlessRequestPriority,
    HeadlessRequestPriorityState,
    HeadlessWorkflowState,
    headless_request_priority_scope,
    headless_workflow_scope,
)
from ironsbot.services.operations.request_feedback import (
    current_request_feedback,
    send_request_feedback,
)

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
    user_id: int | None
    bypass_pause: bool
    background: bool
    timeout_seconds: float | None
    semantic_request: SemanticRequest | None = None
    priority_state: HeadlessRequestPriorityState | None = None
    workflow: HeadlessWorkflowState | None = None
    task: asyncio.Task[Any] | None = None


class PlayerRequestProtectionService:
    """Coordinate semantic player workflows over the shared packet pool."""

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
        self._active: list[_QueuedRequest] = []
        self._by_request_key: dict[tuple[str, str], _QueuedRequest] = {}
        self._workflow_sequence = 0
        self._pause_until = 0.0
        self._last_disconnect_at: float | None = None

    async def run(  # noqa: PLR0913
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        user_id: int | None,
        label: str,
        background: bool = False,
        priority: HeadlessRequestPriority | None = None,
        timeout_seconds: float | None = None,
        semantic_request: SemanticRequest | None = None,
        _retry_after_background_failure: bool = True,
    ) -> T:
        is_superuser = (
            user_id is not None and self._features.is_superuser(user_id)
        )
        request_priority = self._request_priority(
            is_superuser=is_superuser,
            background=background,
            priority=priority,
        )
        if not self._config.enabled:
            await send_request_feedback(queued=False)
            with (
                semantic_request_scope(semantic_request, user_id=user_id),
                headless_request_priority_scope(request_priority),
            ):
                return await operation()

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
                    self._promote(existing, request_priority)
                await send_request_feedback(queued=False)
                try:
                    return cast("T", await asyncio.shield(existing.future))
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

        priority_state = HeadlessRequestPriorityState(request_priority)
        workflow = HeadlessWorkflowState(
            sequence=self._workflow_sequence,
            label=label,
            user_id=user_id,
            priority_state=priority_state,
            feedback=current_request_feedback(),
        )
        self._workflow_sequence += 1
        item = _QueuedRequest(
            label=label,
            operation=cast("Callable[[], Awaitable[Any]]", operation),
            future=asyncio.get_running_loop().create_future(),
            user_id=user_id,
            bypass_pause=bypass_pause,
            background=background,
            timeout_seconds=timeout_seconds,
            semantic_request=semantic_request,
            priority_state=priority_state,
            workflow=workflow,
        )
        self._admit(item)
        if request_key:
            self._by_request_key[request_key] = item
        self._active.append(item)
        logger.info(
            "player workflow admitted: ticket=%s label=%s priority=%s "
            "user=%s background=%s",
            workflow.sequence,
            label,
            request_priority.name.lower(),
            user_id,
            background,
        )
        item.task = self._spawn(
            self._execute(item),
            name=f"seer-player-request:{label}",
        )
        return cast("T", await asyncio.shield(item.future))

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
        paused_error = PlayerRequestPausedError(self.pause_remaining_seconds())
        self._headless.cancel_waiting_background(paused_error)
        for item in tuple(self._active):
            if item.background and item.task is not None:
                item.task.cancel()
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

    def _admit(self, item: _QueuedRequest) -> None:
        state = item.priority_state
        if item.background or state is None:
            return
        if state.priority in (
            HeadlessRequestPriority.SUPERUSER_BASIC,
            HeadlessRequestPriority.SUPERUSER_DETAIL,
        ):
            return
        foreground_capacity = max(1, self._headless.healthy_worker_count)
        active_foreground = sum(
            active.priority_state is not None
            and active.priority_state.priority
            in (
                HeadlessRequestPriority.BASIC,
                HeadlessRequestPriority.INTERACTIVE,
            )
            and not active.future.done()
            for active in self._active
        )
        if (
            active_foreground
            >= foreground_capacity + self._config.max_queued_queries
        ):
            raise PlayerRequestBusyError

    def _request_priority(
        self,
        *,
        is_superuser: bool,
        background: bool,
        priority: HeadlessRequestPriority | None,
    ) -> HeadlessRequestPriority:
        if background:
            return HeadlessRequestPriority.BACKGROUND
        if is_superuser and self._config.superuser_priority:
            if priority is HeadlessRequestPriority.BASIC:
                return HeadlessRequestPriority.SUPERUSER_BASIC
            return HeadlessRequestPriority.SUPERUSER_DETAIL
        if priority is not None:
            return priority
        return HeadlessRequestPriority.INTERACTIVE

    @staticmethod
    def _promote(
        item: _QueuedRequest,
        priority: HeadlessRequestPriority,
    ) -> None:
        """Promote a prefetch; its next packet observes the new priority."""

        item.background = False
        if item.priority_state is not None:
            item.priority_state.promote(priority)

    async def _execute(  # noqa: C901 - lifecycle cleanup is kept in one owner
        self,
        item: _QueuedRequest,
    ) -> None:
        outcome = "cancelled"
        try:
            if self._paused() and item.bypass_pause:
                await self._wait_for_reconnect()
            elif self._paused():
                self._raise_paused()
            priority_state = item.priority_state or HeadlessRequestPriorityState(
                HeadlessRequestPriority.INTERACTIVE
            )
            with (
                semantic_request_scope(
                    item.semantic_request,
                    user_id=item.user_id,
                ),
                headless_request_priority_scope(
                    priority_state.priority,
                    state=priority_state,
                ),
                headless_workflow_scope(
                    item.workflow
                    or HeadlessWorkflowState(
                        sequence=-1,
                        label=item.label,
                        user_id=item.user_id,
                        priority_state=priority_state,
                    ),
                ),
            ):
                result = await self._run_operation(item)
        except asyncio.CancelledError:
            item.future.cancel()
            raise
        except asyncio.TimeoutError as error:
            outcome = "timed_out"
            logger.warning(
                "player request timed out: label=%s background=%s timeout=%.1fs",
                item.label,
                item.background,
                item.timeout_seconds or 0.0,
            )
            if not item.future.done():
                item.future.set_exception(error)
        except Exception as error:  # noqa: BLE001
            outcome = type(error).__name__
            if not item.future.done():
                item.future.set_exception(error)
        else:
            outcome = "completed"
            if not item.future.done():
                item.future.set_result(result)
        finally:
            workflow = item.workflow
            if workflow is not None:
                logger.info(
                    "player workflow finished: ticket=%s label=%s priority=%s "
                    "user=%s packets=%s queued_packets=%s elapsed=%.3fs outcome=%s",
                    workflow.sequence,
                    workflow.label,
                    workflow.priority_state.priority.name.lower(),
                    workflow.user_id,
                    workflow.packet_count,
                    workflow.queued_packet_count,
                    monotonic() - workflow.queued_at,
                    outcome,
                )
            if item in self._active:
                self._active.remove(item)
            self._release_request_key(item)

    async def _run_operation(  # noqa: C901 - timeout ownership stays centralized
        self,
        item: _QueuedRequest,
    ) -> Any:
        if item.timeout_seconds is None:
            return await item.operation()

        async def execute_operation() -> Any:
            return await item.operation()

        operation_task = self._spawn(
            execute_operation(),
            name=f"seer-player-request-operation:{item.label}",
        )
        workflow = item.workflow
        if workflow is None:
            try:
                return await asyncio.wait_for(
                    asyncio.shield(operation_task),
                    timeout=item.timeout_seconds,
                )
            except (asyncio.CancelledError, asyncio.TimeoutError):
                operation_task.cancel()
                raise

        submitted_task = self._spawn(
            workflow.packet_submitted.wait(),
            name=f"seer-player-workflow-submitted:{item.label}",
        )
        start_task: asyncio.Task[Any] | None = None
        try:
            done, _pending = await asyncio.wait(
                {operation_task, submitted_task},
                return_when=asyncio.FIRST_COMPLETED,
                timeout=item.timeout_seconds,
            )
            if operation_task in done:
                return operation_task.result()
            if not done:
                self._raise_operation_timeout()
            start_task = self._spawn(
                workflow.started.wait(),
                name=f"seer-player-workflow-start:{item.label}",
            )
            done, _pending = await asyncio.wait(
                {operation_task, start_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if operation_task in done:
                return operation_task.result()
            return await asyncio.wait_for(
                asyncio.shield(operation_task),
                timeout=item.timeout_seconds,
            )
        except (asyncio.CancelledError, asyncio.TimeoutError):
            operation_task.cancel()
            raise
        finally:
            if not submitted_task.done():
                submitted_task.cancel()
            if start_task is not None and not start_task.done():
                start_task.cancel()

    @staticmethod
    def _raise_operation_timeout() -> NoReturn:
        raise asyncio.TimeoutError

    async def _wait_for_reconnect(self) -> None:
        try:
            await self._headless.wait_until_available(
                timeout=max(self._config.disconnect_pause_seconds, 1.0)
            )
        except Exception as error:
            raise PlayerRequestReconnectError from error

    def _raise_paused(self) -> NoReturn:
        raise PlayerRequestPausedError(self.pause_remaining_seconds())

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
