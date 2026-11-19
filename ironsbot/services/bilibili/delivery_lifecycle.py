# SPDX-License-Identifier: MIT
"""One dynamic owner and bounded per-target stage execution."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ironsbot.core.delivery_attempt import (
    DeliveryProgress,
    delivery_execution,
    delivery_progress,
)
from ironsbot.core.outbound import DeliveryFailureKind, SendResult

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from ironsbot.core.platform import ConversationRef
    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.services.bilibili.delivery_ledger import DynamicDeliveryLedger

STAGE_DEADLINE_SECONDS = 60.0
MAX_STAGE_ATTEMPTS = 4
LEASE_RENEW_SECONDS = 10.0
_LOGGER = logging.getLogger(__name__)
_WORKERS: set[asyncio.Future[None]] = set()
_WorkerMap = dict[asyncio.Future[None], tuple["ConversationRef", DeliveryProgress]]
_OWNED_WORKERS: ContextVar[_WorkerMap | None] = ContextVar(
    "bilibili_owned_workers", default=None
)
_OWNER_GATE: ContextVar[DeliveryProgress | None] = ContextVar(
    "bilibili_owner_gate", default=None
)


class DeliveryOwnershipLostError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Bilibili execution ownership is no longer reliable")


def has_pending_workers(target: ConversationRef) -> bool:
    workers = _OWNED_WORKERS.get()
    return workers is not None and any(
        value[0] == target and not task.done() for task, value in workers.items()
    )


def _renew_owner(ledger: DynamicDeliveryLedger, key: str, owner: str) -> bool:
    try:
        renewed = ledger.renew_execution(key, owner)
    except Exception as error:  # noqa: BLE001 - ownership uncertainty must close action gates
        _LOGGER.error(  # noqa: TRY400 - log type only, not arbitrary storage exception text
            "Bilibili execution renewal failed: dynamic=%s exception=%s",
            key,
            type(error).__name__,
        )
        return False
    if not renewed:
        _LOGGER.error("Bilibili execution ownership lost: dynamic=%s", key)
    return renewed


def _stop_workers(workers: _WorkerMap) -> None:
    for task, (_, progress) in tuple(workers.items()):
        progress.close()
        task.cancel()


async def drain_owned_workers() -> None:
    workers = _OWNED_WORKERS.get()
    if not workers:
        return
    drained = asyncio.gather(*workers, return_exceptions=True)
    cancelled = False
    while not drained.done():
        try:
            await asyncio.shield(drained)
        except asyncio.CancelledError:  # noqa: PERF203 - repeated cancellation must not release active transports
            cancelled = True
    drained.result()
    if cancelled:
        raise asyncio.CancelledError


def _drained(task: asyncio.Future[None]) -> None:
    _WORKERS.discard(task)
    if not task.cancelled():
        task.exception()


@asynccontextmanager
async def own_delivery(
    ledger: DynamicDeliveryLedger | None,
    key: str,
    *,
    on_release: Callable[[], None] | None = None,
) -> AsyncIterator[bool]:
    if ledger is None:
        yield True
        return
    owner = uuid.uuid4().hex
    if not ledger.acquire_execution(key, owner):
        _LOGGER.info("Bilibili execution already owned: dynamic=%s", key)
        yield False
        return
    stop = asyncio.Event()
    workers: _WorkerMap = {}
    owner_gate = DeliveryProgress()

    async def heartbeat() -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=LEASE_RENEW_SECONDS)
            except asyncio.TimeoutError:  # noqa: PERF203 - periodic durable lease renewal
                if not _renew_owner(ledger, key, owner):
                    owner_gate.close()
                    _stop_workers(workers)
                    return

    # This child is scoped to the context and joined before releasing it.
    task = asyncio.ensure_future(heartbeat())
    marker = delivery_execution.set((key, owner))
    worker_marker = _OWNED_WORKERS.set(workers)
    gate_marker = _OWNER_GATE.set(owner_gate)

    try:
        yield True
    finally:
        try:
            await drain_owned_workers()
        finally:
            _OWNED_WORKERS.reset(worker_marker)
            _OWNER_GATE.reset(gate_marker)
            delivery_execution.reset(marker)
            stop.set()
            try:
                await task
            finally:
                ledger.release_execution(key, owner)
                current = asyncio.current_task()
                if on_release is not None and (
                    current is None or not current.cancelling()
                ):
                    on_release()


@dataclass(slots=True)
class OrderedStages:
    ledger: DynamicDeliveryLedger | None
    dynamic_id: str
    failures: dict[tuple[ConversationRef, str], SendResult]
    completed: set[tuple[ConversationRef, str]]
    deadlines: dict[tuple[ConversationRef, str], float] = field(default_factory=dict)
    spawn: TaskSpawner | None = None

    def record_completion(self, target: ConversationRef, stage: str) -> None:
        if self.ledger is None and (target, stage) not in self.failures:
            self.completed.add((target, stage))

    def advance(self, target: ConversationRef, stage: str) -> bool:
        if self.ledger is not None:
            state = self.ledger.stage_state(self.dynamic_id, target, stage)
            if state == "uncertain":
                self.ledger.block_following(self.dynamic_id, target, stage)
            return state in {"success", "failed", "skipped", "expired", "delegated"}
        result = self.failures.get((target, stage))
        return (
            result is None
            or result.failure_kind is DeliveryFailureKind.PERMANENT
            or (
                result.failure_kind is DeliveryFailureKind.RETRYABLE
                and result.attempt_count >= MAX_STAGE_ATTEMPTS
            )
        )

    def remaining(self, target: ConversationRef, stage: str) -> float:
        if self.ledger is not None:
            return self.ledger.start_stage(self.dynamic_id, target, stage)
        key = (target, stage)
        end = self.deadlines.setdefault(key, time.monotonic() + STAGE_DEADLINE_SECONDS)
        return max(0.0, end - time.monotonic())

    def failed(self, target: ConversationRef, stage: str) -> bool:
        return (
            self.ledger is not None
            and self.ledger.stage_state(self.dynamic_id, target, stage) == "failed"
        )

    def expire(self, target: ConversationRef, stage: str) -> None:
        if self.ledger is not None:
            self.ledger.expire_stage(self.dynamic_id, target, stage)
            if result := self.ledger.stage_result(self.dynamic_id, target, stage):
                self.failures[(target, stage)] = result
            if self.ledger.stage_state(self.dynamic_id, target, stage) == "uncertain":
                self.ledger.block_following(self.dynamic_id, target, stage)
            return
        self.failures[(target, stage)] = SendResult(
            delivered=False,
            error_code="stage_deadline_inflight",
            failure_kind=DeliveryFailureKind.UNCERTAIN,
        )

    async def run(
        self,
        target: ConversationRef,
        stage: str,
        operation: Callable[[], Awaitable[None]],
    ) -> None:
        if (owner_gate := _OWNER_GATE.get()) is not None and owner_gate.closed:
            raise DeliveryOwnershipLostError
        seconds = self.remaining(target, stage)
        if seconds <= 0:
            self.expire(target, stage)
            return

        async def execute() -> None:
            await operation()

        progress = DeliveryProgress(deadline=time.monotonic() + seconds)
        marker = delivery_progress.set(progress)
        try:
            worker = (
                self.spawn(execute(), name="bilibili.unit.receipt")
                if self.spawn
                else asyncio.ensure_future(execute())
            )
        finally:
            delivery_progress.reset(marker)
        _WORKERS.add(worker)
        worker.add_done_callback(_drained)
        if (owned_workers := _OWNED_WORKERS.get()) is not None:
            owned_workers[worker] = (target, progress)
        try:
            await asyncio.wait_for(asyncio.shield(worker), timeout=seconds)
        except asyncio.TimeoutError:
            if worker.done():
                worker.result()
                return
            progress.close()
            if progress.safe_to_retry and self.ledger is not None:
                self.ledger.finish(
                    self.dynamic_id,
                    target,
                    stage,
                    SendResult(
                        delivered=False,
                        error_code="stage_deadline_before_submit",
                        failure_kind=DeliveryFailureKind.PERMANENT,
                        failure_phase=progress.phase,
                    ),
                )
            self.expire(target, stage)
        except asyncio.CancelledError:
            progress.close()
            if not progress.safe_to_retry:
                self.expire(target, stage)
            raise
