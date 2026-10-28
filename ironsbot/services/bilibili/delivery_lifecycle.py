# SPDX-License-Identifier: MIT
"""One dynamic owner and bounded per-target stage execution."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ironsbot.core.delivery_attempt import delivery_execution
from ironsbot.core.outbound import DeliveryFailureKind, SendResult

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from ironsbot.core.platform import ConversationRef
    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.services.bilibili.delivery_ledger import DynamicDeliveryLedger

STAGE_DEADLINE_SECONDS = 60.0
MAX_STAGE_ATTEMPTS = 4
_LOGGER = logging.getLogger(__name__)
_WORKERS: set[asyncio.Future[None]] = set()


def _drained(task: asyncio.Future[None]) -> None:
    _WORKERS.discard(task)
    if not task.cancelled():
        task.exception()


@asynccontextmanager
async def own_delivery(
    ledger: DynamicDeliveryLedger | None, key: str
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

    async def heartbeat() -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=10.0)
            except asyncio.TimeoutError:  # noqa: PERF203 - periodic durable lease renewal
                if not ledger.renew_execution(key, owner):
                    return

    # This child is scoped to the context and joined before releasing it.
    task = asyncio.ensure_future(heartbeat())
    marker = delivery_execution.set((key, owner))
    try:
        yield True
    finally:
        delivery_execution.reset(marker)
        stop.set()
        try:
            await task
        finally:
            ledger.release_execution(key, owner)


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
        seconds = self.remaining(target, stage)
        if seconds <= 0:
            self.expire(target, stage)
            return

        async def execute() -> None:
            await operation()

        worker = (
            self.spawn(execute(), name="bilibili.unit.receipt")
            if self.spawn
            else asyncio.ensure_future(execute())
        )
        _WORKERS.add(worker)
        worker.add_done_callback(_drained)
        try:
            await asyncio.wait_for(asyncio.shield(worker), timeout=seconds)
        except asyncio.TimeoutError:
            if worker.done():
                worker.result()
                return
            self.expire(target, stage)
        except asyncio.CancelledError:
            self.expire(target, stage)
            raise
