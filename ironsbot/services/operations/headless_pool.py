# SPDX-License-Identifier: MIT
"""Persistent, independently logged-in headless Seer worker pool."""

from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.services.operations.headless import (
        HeadlessGame,
        HeadlessService,
        HeadlessStateListener,
    )

T = TypeVar("T")
logger = logging.getLogger(__name__)
_CURRENT_WORKER: ContextVar["HeadlessWorker | None"] = ContextVar(
    "current_headless_worker",
    default=None,
)


@dataclass(slots=True)
class HeadlessWorker:
    key: str
    service: HeadlessService
    busy: bool = False


class HeadlessPoolError(RuntimeError):
    @classmethod
    def missing_primary_worker(cls) -> HeadlessPoolError:
        return cls("headless pool needs a primary worker")

    @classmethod
    def reconnect_timeout(cls) -> HeadlessPoolError:
        return cls("headless workers did not reconnect in time")


class HeadlessPool:
    """Route one live workflow to one isolated account for its full lifetime."""

    def __init__(self, workers: tuple[HeadlessWorker, ...]) -> None:
        if not workers:
            raise HeadlessPoolError.missing_primary_worker()
        self._workers = workers
        self._next_index = 0

    @property
    def primary(self) -> HeadlessService:
        return self._workers[0].service

    @property
    def configured(self) -> bool:
        return any(worker.service.configured for worker in self._workers)

    @property
    def user_id_text(self) -> str:
        return self.primary.user_id_text

    @property
    def reconnect_times(self) -> list[str]:
        return self.primary.reconnect_times

    @property
    def worker_count(self) -> int:
        return len(self._workers)

    @property
    def busy_count(self) -> int:
        return sum(worker.busy for worker in self._workers)

    def get_game(self) -> HeadlessGame:
        worker = _CURRENT_WORKER.get()
        return (worker.service if worker is not None else self.primary).get_game()

    def login_failure_reason(self) -> str | None:
        return self.primary.login_failure_reason()

    def add_state_listener(self, listener: HeadlessStateListener) -> None:
        for worker in self._workers:
            worker.service.add_state_listener(listener)

    def has_available_worker(self) -> bool:
        for worker in self._workers:
            if worker.busy or not worker.service.configured:
                continue
            try:
                worker.service.get_game()
            except (DisconnectedError, NotLoggedInError):
                continue
            return True
        return False

    def has_connected_worker(self) -> bool:
        for worker in self._workers:
            if not worker.service.configured:
                continue
            try:
                worker.service.get_game()
            except (DisconnectedError, NotLoggedInError):
                continue
            return True
        return False

    def try_acquire(self) -> HeadlessWorker | None:
        """Reserve a worker synchronously for the pool scheduler."""

        count = len(self._workers)
        fallback: HeadlessWorker | None = None
        for offset in range(count):
            position = (self._next_index + offset) % count
            worker = self._workers[position]
            if worker.busy or not worker.service.configured:
                continue
            if fallback is None:
                fallback = worker
            try:
                worker.service.get_game()
            except (DisconnectedError, NotLoggedInError):
                continue
            worker.busy = True
            self._next_index = (position + 1) % count
            logger.debug("headless worker acquired: worker=%s", worker.key)
            return worker
        if fallback is None:
            return None
        fallback.busy = True
        logger.debug(
            "headless worker acquired while unavailable: worker=%s",
            fallback.key,
        )
        return fallback

    async def run_on(
        self,
        worker: HeadlessWorker,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        token = _CURRENT_WORKER.set(worker)
        try:
            return await operation()
        finally:
            _CURRENT_WORKER.reset(token)
            self.release(worker)

    @staticmethod
    def release(worker: HeadlessWorker) -> None:
        worker.busy = False
        logger.debug("headless worker released: worker=%s", worker.key)

    async def start(self) -> None:
        for worker in self._workers:
            logger.info("starting headless worker: worker=%s", worker.key)
            await worker.service.start()

    async def shutdown(self) -> None:
        await asyncio.gather(*(worker.service.shutdown() for worker in self._workers))

    async def check_on_connect(self) -> None:
        for worker in self._workers:
            await worker.service.check_on_connect()

    async def reconnect(self, scheduled_time: str) -> None:
        for worker in self._workers:
            await worker.service.reconnect(scheduled_time)

    async def wait_until_available(self, *, timeout: float) -> HeadlessGame:
        try:
            return self.get_game()
        except (DisconnectedError, NotLoggedInError):
            pass
        waits = [
            worker.service.wait_until_available(timeout=timeout)
            for worker in self._workers
            if worker.service.configured
        ]
        if not waits:
            return await self.primary.wait_until_available(timeout=timeout)
        tasks = [asyncio.create_task(wait) for wait in waits]
        try:
            done, _pending = await asyncio.wait(
                tasks,
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                raise HeadlessPoolError.reconnect_timeout()
            return next(iter(done)).result()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

    async def mark_available(
        self,
        *,
        source: str,
        user_id: int | None = None,
    ) -> None:
        worker = _CURRENT_WORKER.get()
        await (worker.service if worker is not None else self.primary).mark_available(
            source=source,
            user_id=user_id,
        )

    async def mark_unavailable(self, reason: str, *, source: str) -> None:
        worker = _CURRENT_WORKER.get()
        await (worker.service if worker is not None else self.primary).mark_unavailable(
            reason,
            source=source,
        )
