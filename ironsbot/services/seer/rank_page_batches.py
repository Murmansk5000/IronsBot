# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded, ordered page batches sharing the public headless dispatcher."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from itertools import islice
from typing import TYPE_CHECKING

from ironsbot.core.rank_lookup_context import RankPagePolicy, rank_page_policy

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterable

    from ironsbot.services.seer.rank_models import RankPageResult

MAX_PARALLEL_PAGES = 3


@dataclass(slots=True)
class RankProbePages:
    """Share overlapping point probes without reusing evidence in tie validation."""

    fetch: Callable[[int], Awaitable[RankPageResult]]
    _pages: dict[int, RankPageResult] = field(default_factory=dict)
    _locks: dict[int, asyncio.Lock] = field(default_factory=dict)

    async def __call__(self, start: int) -> RankPageResult:
        async with self._locks.setdefault(start, asyncio.Lock()):
            if start not in self._pages:
                self._pages[start] = await self.fetch(start)
            return self._pages[start]


async def ordered_page_batches(
    starts: Iterable[int],
    fetch: Callable[[int], Awaitable[RankPageResult]],
    parallelism: Callable[[], int] | None,
    *,
    phase: str,
) -> AsyncIterator[tuple[int, RankPageResult]]:
    remaining = iter(starts)
    while batch := tuple(
        islice(
            remaining,
            max(1, min(MAX_PARALLEL_PAGES, parallelism() if parallelism else 1)),
        )
    ):
        token = rank_page_policy.set(RankPagePolicy(phase, parallel=True))
        try:
            pages = await asyncio.gather(
                *(fetch(start) for start in batch), return_exceptions=True
            )
        finally:
            rank_page_policy.reset(token)
        for start, page in zip(batch, pages, strict=True):
            if isinstance(page, BaseException):
                raise page
            yield start, page
