# SPDX-License-Identifier: GPL-3.0-or-later
"""Request-local rank pages, bounded prefix mapping and one conflict recovery."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

from ironsbot.core.rank_lookup_context import RankPagePolicy, rank_page_policy
from ironsbot.core.time import ObservationTime
from ironsbot.services.seer.rank_list_models import GLOBAL_RANKS
from ironsbot.services.seer.rank_models import RankPageResult, RankRangeResult
from ironsbot.services.seer.rank_pagination import (
    RankPageConflictError,
    RankPageSequence,
    rank_conflict_retry_used,
)
from ironsbot.services.seer.rank_visibility import (
    EXCLUSION_PREFIX_SIZE,
    RankVisibility,
    uses_filtered_prefix,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

T = TypeVar("T")
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RankVisibilityQuery:
    service: Any
    game: Any
    rank_key: str | None
    key: int
    sub_key: int
    pages: dict[int, RankPageResult] = field(default_factory=dict)
    prefix: list[Any] = field(default_factory=list)
    retried: bool = field(default_factory=rank_conflict_retry_used.get)
    prefix_pages: int = 0
    target_pages: int = 0
    target_starts: set[int] = field(default_factory=set)
    prefix_limit: int = EXCLUSION_PREFIX_SIZE
    public_until: int | None = None
    started: float = field(default_factory=time.monotonic)

    @property
    def ascending(self) -> bool:
        spec = GLOBAL_RANKS.get(self.rank_key) if self.rank_key is not None else None
        return spec.ascending if spec is not None else False

    async def recover(self, phase: str, operation: Callable[[], Awaitable[T]]) -> T:
        while True:
            try:
                return await operation()
            except RankPageConflictError as error:  # noqa: PERF203 - at most one bounded network retry
                logger.warning(
                    "rank visibility conflict: key=%s sub_key=%s "
                    "phase=%s retry=%s page_start=%s",
                    self.key,
                    self.sub_key,
                    phase,
                    int(self.retried),
                    error.page_start,
                )
                if self.retried:
                    raise
                self.retried = True
                self.pages = {
                    start: page
                    for start, page in self.pages.items()
                    if start not in self.target_starts
                }
                if phase == "prefix":
                    self.pages.clear()
                    self.prefix.clear()

    async def page(self, start: int, phase: str) -> RankPageResult:
        if phase == "target":
            self.target_starts.add(start)
        if start not in self.pages:
            token = (
                rank_page_policy.set(RankPagePolicy("exclusion_prefix"))
                if phase == "prefix"
                else None
            )
            try:
                page = await self.service.fetch_page_result(
                    self.game,
                    key=self.key,
                    sub_key=self.sub_key,
                    start=start,
                    end=start + self.service.page_size() - 1,
                    use_cache=False,
                )
            finally:
                if token is not None:
                    rank_page_policy.reset(token)
            self.pages[start] = page
            if phase == "prefix":
                self.prefix_pages += 1
            else:
                self.target_pages += 1
        return self.pages[start]

    async def visibility(
        self, *, public_until: int | None = None, raw_until: int | None = None
    ) -> RankVisibility:
        ids = (
            self.service.exclusion_policy.excluded_user_ids(self.rank_key)
            if self.rank_key is not None
            else frozenset()
        )
        self.public_until = public_until
        self.prefix_limit = (
            min(EXCLUSION_PREFIX_SIZE, raw_until)
            if raw_until is not None
            else EXCLUSION_PREFIX_SIZE
        )
        if uses_filtered_prefix(self.rank_key) and ids:
            await self.recover("prefix", self.read_prefix)
        return RankVisibility.build(self.rank_key, ids, self.prefix)

    async def read_prefix(self) -> None:
        self.prefix = []
        sequence = RankPageSequence(ascending=self.ascending)
        size = self.service.page_size()
        ids = self.service.exclusion_policy.excluded_user_ids(self.rank_key)
        visible_count = 0
        for start in range(0, self.prefix_limit, size):
            page = await self.page(start, "prefix")
            items = page.items[: EXCLUSION_PREFIX_SIZE - start]
            self.include(sequence, items, start)
            self.prefix.extend(items)
            visible_count += sum(int(item.id) not in ids for item in items)
            if self.public_until is not None and visible_count >= self.public_until:
                break
            if len(page.items) < size:
                break

    async def raw_range(self, start: int, count: int) -> RankRangeResult:
        size = self.service.page_size()
        end = start + count
        items: list[Any] = []
        observation = ObservationTime()
        sequence = RankPageSequence(ascending=self.ascending)
        from_cache = True
        for page_start in range(start // size * size, end, size):
            page = await self.page(page_start, "target")
            self.include(sequence, page.items, page_start)
            observation.include(page.fetched_at)
            from_cache = from_cache and page.from_cache
            items.extend(
                item
                for offset, item in enumerate(page.items)
                if start <= page_start + offset < end
            )
            if len(page.items) < size:
                break
        return RankRangeResult(items, observation.fetched_at, from_cache)

    @staticmethod
    def include(sequence: RankPageSequence, items: list[Any], start: int) -> None:
        try:
            sequence.include((int(item.id), int(item.score)) for item in items)
        except RankPageConflictError as error:
            error.page_start = start
            raise

    async def range(self, start_rank: int, count: int) -> RankRangeResult:
        first = max(0, start_rank - 1)
        if count <= 0:
            return RankRangeResult([], None, ranks=[])
        visibility = await self.visibility(public_until=first + count)
        raw_first = visibility.raw_index(first)
        raw_last = visibility.raw_index(first + count - 1)

        async def read() -> RankRangeResult:
            nonlocal visibility, raw_first, raw_last
            if (
                self.retried
                and self.prefix
                and any(start < len(self.prefix) for start in self.target_starts)
            ):
                visibility = await self.visibility(public_until=first + count)
                raw_first = visibility.raw_index(first)
                raw_last = visibility.raw_index(first + count - 1)
            result = await self.raw_range(raw_first, raw_last - raw_first + 1)
            # Validate across the prefix/target boundary, but never duplicate
            # overlapping positions already read in the same request.
            if self.prefix and raw_last >= len(self.prefix):
                sequence = RankPageSequence(ascending=self.ascending)
                sequence.include(
                    (int(item.id), int(item.score)) for item in self.prefix
                )
                sequence.include(
                    (int(item.id), int(item.score))
                    for offset, item in enumerate(result.items)
                    if raw_first + offset >= len(self.prefix)
                )
            rows = [
                (visibility.public_index(raw_first + offset) + 1, item)
                for offset, item in enumerate(result.items)
                if not visibility.hides(raw_first + offset, int(item.id))
            ]
            result.items = [item for _, item in rows]
            result.ranks = [rank for rank, _ in rows]
            if self.prefix:
                observation = ObservationTime()
                observation.include(result.fetched_at)
                for page_start, page in self.pages.items():
                    if page_start < EXCLUSION_PREFIX_SIZE:
                        observation.include(page.fetched_at)
                result.fetched_at = observation.fetched_at
            return result

        result = await self.recover("target", read)
        self.log_complete(visibility, start_rank=start_rank, count=count)
        return result

    def log_complete(
        self, visibility: RankVisibility, *, start_rank: int | None, count: int
    ) -> None:
        logger.info(
            "rank visibility complete: key=%s sub_key=%s strategy=%s start=%s count=%s "
            "prefix_pages=%s target_pages=%s hidden=%s retry=%s elapsed=%.3fs",
            self.key,
            self.sub_key,
            "filtered_prefix" if visibility.filtered_prefix else "official",
            start_rank,
            count,
            self.prefix_pages,
            self.target_pages,
            len(visibility.hidden_indexes),
            int(self.retried),
            time.monotonic() - self.started,
        )
