# SPDX-License-Identifier: GPL-3.0-or-later
"""Successful, dated observations with cancellation-safe shared reads."""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING, Any, TypeVar

from ironsbot.core import time as clock
from ironsbot.core.platform import reference_digest
from ironsbot.core.time import ObservationTime, remaining_observation_ttl

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Hashable

    from ironsbot.core.tasks import TaskSpawner

T = TypeVar("T")
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CachedObservation:
    value: Any
    fetched_at: float


class ObservationCache:
    def __init__(self, spawn: TaskSpawner | None = None) -> None:
        self._spawn = spawn
        self._values: dict[Hashable, CachedObservation] = {}
        self._pending: dict[Hashable, asyncio.Task[CachedObservation]] = {}
        self._waiters: dict[Hashable, int] = {}
        self._failures: dict[Hashable, float] = {}

    def get(self, key: Hashable, ttl: float) -> CachedObservation | None:
        stamp = clock.now().timestamp()
        for old_key, failed_at in tuple(self._failures.items()):
            if remaining_observation_ttl(failed_at, ttl, at=stamp) <= 0:
                self._failures.pop(old_key, None)
        # Expiration never extends on a read, and old entries do not accumulate.
        for old_key, item in tuple(self._values.items()):
            if remaining_observation_ttl(item.fetched_at, ttl, at=stamp) <= 0:
                self._values.pop(old_key, None)
        item = self._values.get(key)
        return deepcopy(item) if item is not None else None

    def discard(self, key: Hashable) -> None:
        self._values.pop(key, None)

    def save(self, key: Hashable, value: Any, fetched_at: float | None) -> None:
        if fetched_at is not None:
            previous = self._values.get(key)
            if previous is not None and previous.fetched_at > fetched_at:
                return
            self._values[key] = CachedObservation(deepcopy(value), fetched_at)
            self._failures.pop(key, None)

    def inflight(self, key: Hashable) -> bool:
        return key in self._pending

    async def observe(
        self,
        key: Hashable,
        fetch: Callable[[], Awaitable[T]],
        *,
        ttl: float,
        observation: ObservationTime,
    ) -> T:
        reason = "expired" if key in self._values else "missing"
        if key in self._failures:
            reason = "previous_failure"
        cached = self.get(key, ttl)
        if cached is not None:
            logger.info(
                "player observation reused: project=%s project_ref=%s age=%.3fs",
                _project_label(key),
                reference_digest(str(key)),
                clock.now().timestamp() - cached.fetched_at,
            )
            observation.include(cached.fetched_at)
            return cached.value

        async def load() -> CachedObservation:
            logger.info(
                "player observation fetching: project=%s project_ref=%s reason=%s",
                _project_label(key),
                reference_digest(str(key)),
                reason,
            )
            value = await fetch()
            item = CachedObservation(value, clock.now().timestamp())
            self.save(key, value, item.fetched_at)
            return item

        item = await self.share(key, load)
        observation.include(item.fetched_at)
        return deepcopy(item.value)

    async def share(
        self,
        key: Hashable,
        fetch: Callable[[], Awaitable[CachedObservation]],
    ) -> CachedObservation:
        if self._spawn is None:
            return await fetch()
        pending = self._pending.get(key)
        if pending is None:

            async def load() -> CachedObservation:
                started = monotonic()
                try:
                    return await fetch()
                except Exception as error:
                    self._failures[key] = clock.now().timestamp()
                    logger.info(
                        "player observation failed: project=%s project_ref=%s "
                        "error_type=%s",
                        _project_label(key),
                        reference_digest(str(key)),
                        type(error).__name__,
                    )
                    raise
                finally:
                    self._pending.pop(key, None)
                    logger.info(
                        "player observation finished: project=%s project_ref=%s "
                        "elapsed=%.3fs",
                        _project_label(key),
                        reference_digest(str(key)),
                        monotonic() - started,
                    )

            pending = self._spawn(
                load(),
                name=f"seer-observation-{reference_digest(str(key))}",
            )
            self._pending[key] = pending
            pending.add_done_callback(_consume_exception)
        else:
            logger.info(
                "player observation awaiting shared read: project=%s project_ref=%s",
                _project_label(key),
                reference_digest(str(key)),
            )
        self._waiters[key] = self._waiters.get(key, 0) + 1
        try:
            return deepcopy(await asyncio.shield(pending))
        finally:
            remaining = self._waiters[key] - 1
            if remaining:
                self._waiters[key] = remaining
            else:
                self._waiters.pop(key, None)
                if not pending.done():
                    pending.cancel()


def _consume_exception(task: asyncio.Task[CachedObservation]) -> None:
    if not task.cancelled():
        task.exception()


def _project_label(key: Hashable) -> str:
    return str(key[1]) if isinstance(key, tuple) and len(key) > 1 else "observation"
