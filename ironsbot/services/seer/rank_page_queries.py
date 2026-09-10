# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
import time
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from ironsbot.core.rank_lookup_context import rank_query_id
from ironsbot.services.seer.rank_diagnostics import (
    diagnose_rank_query,
    observe_rank_page,
)
from ironsbot.services.seer.rank_exclusion_lookups import fetch_visible_rank_range
from ironsbot.services.seer.rank_models import RankPageResult
from ironsbot.services.seer.rank_player_scheduler import (
    PlayerRankPagePriority,
    current_player_rank_page_scheduler,
)
from ironsbot.services.seer.rank_range import fetch_rank_range, fetch_rank_range_result
from ironsbot.services.seer.rank_work_cache import record_rank_page_work

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from ironsbot.config.models.seer import RankQueryConfig
    from ironsbot.services.operations.headless import HeadlessGame
    from ironsbot.services.seer.rank import RankPageCache
    from ironsbot.services.seer.rank_exclusions import RankExclusionPolicy
    from ironsbot.services.seer.rank_models import RankEntry

_PARALLEL_RANK_PAGE_REQUEST: ContextVar[bool] = ContextVar(
    "parallel_rank_page_request",
    default=False,
)
_LOGGER = logging.getLogger("ironsbot.seer.rank")


class RankPageQueryMixin:
    config: RankQueryConfig
    cache: RankPageCache
    fetch_online_page: Callable[..., Awaitable[list[RankEntry]]]

    @property
    def exclusion_policy(self) -> RankExclusionPolicy:
        raise NotImplementedError

    def page_size(self) -> int:
        raise NotImplementedError

    def page_start(self, index: int) -> int:
        raise NotImplementedError

    async def fetch_page_result(  # noqa: PLR0913
        self,
        game: HeadlessGame,
        *,
        key: int,
        sub_key: int,
        start: int,
        end: int,
        use_cache: bool = False,
        parallel: bool = False,
        page_phase: str = "search",
        page_priority: PlayerRankPagePriority = PlayerRankPagePriority.SEARCH,
        page_timeout_seconds: float | None = None,
        page_max_retries: int | None = None,
    ) -> RankPageResult:
        if use_cache:
            cached = self.cache.page(
                key=key,
                sub_key=sub_key,
                start=start,
                end=end,
            )
            if cached is not None:
                observe_rank_page(
                    self.exclusion_policy,
                    key=key,
                    sub_key=sub_key,
                    start=start,
                    end=end,
                    items=list(cached.items),
                    fetched_at=cached.fetched_at,
                    cached=True,
                )
                record_rank_page_work(
                    self.exclusion_policy,
                    key=key,
                    sub_key=sub_key,
                    cached=True,
                )
                return RankPageResult(
                    list(cached.items),
                    cached.fetched_at,
                    from_cache=True,
                )

        query_id = rank_query_id.get()

        async def fetch_online() -> list[RankEntry]:
            token = rank_query_id.set(query_id)
            try:
                return await self.fetch_online_page(
                    game,
                    key=key,
                    sub_key=sub_key,
                    start=start,
                    end=end,
                )
            finally:
                rank_query_id.reset(token)

        scheduler = current_player_rank_page_scheduler()
        started_at = time.monotonic()
        try:
            if scheduler is None:
                items = await fetch_online()
            elif parallel:
                items = await scheduler.fetch_parallel_page(
                    (
                        f"{page_phase}:key={key} sub_key={sub_key} "
                        f"page={start + 1}-{end + 1}"
                    ),
                    fetch_online,
                    priority=page_priority,
                    phase=page_phase,
                    timeout_seconds=page_timeout_seconds,
                    max_retries=page_max_retries,
                )
            else:
                items = await scheduler.fetch_page(
                    (
                        f"{page_phase}:key={key} sub_key={sub_key} "
                        f"page={start + 1}-{end + 1}"
                    ),
                    fetch_online,
                    priority=page_priority,
                    phase=page_phase,
                    timeout_seconds=page_timeout_seconds,
                    max_retries=page_max_retries,
                )
        except Exception as error:
            _LOGGER.info(
                "player rank page result: query=%s phase=%s key=%s sub_key=%s "
                "page=%s-%s elapsed=%.3fs error=%s",
                query_id,
                page_phase,
                key,
                sub_key,
                start + 1,
                end + 1,
                time.monotonic() - started_at,
                type(error).__name__,
            )
            raise
        _LOGGER.info(
            "player rank page result: query=%s phase=%s key=%s sub_key=%s "
            "page=%s-%s elapsed=%.3fs items=%s",
            query_id,
            page_phase,
            key,
            sub_key,
            start + 1,
            end + 1,
            time.monotonic() - started_at,
            len(items),
        )
        fetched_at = time.time()
        observe_rank_page(
            self.exclusion_policy,
            key=key,
            sub_key=sub_key,
            start=start,
            end=end,
            items=items,
            fetched_at=fetched_at,
            cached=False,
        )
        self.cache.save(
            key=key,
            sub_key=sub_key,
            start=start,
            end=end,
            items=items,
            fetched_at=fetched_at,
        )
        record_rank_page_work(
            self.exclusion_policy,
            key=key,
            sub_key=sub_key,
            cached=False,
        )
        return RankPageResult(items, fetched_at, from_cache=False)

    async def fetch_page(  # noqa: PLR0913
        self,
        game: HeadlessGame,
        *,
        key: int,
        sub_key: int,
        start: int,
        end: int,
        use_cache: bool = False,
        parallel: bool = False,
        page_phase: str = "search",
        page_priority: PlayerRankPagePriority = PlayerRankPagePriority.SEARCH,
        page_timeout_seconds: float | None = None,
        page_max_retries: int | None = None,
    ) -> list[Any]:
        parallel = parallel or _PARALLEL_RANK_PAGE_REQUEST.get()
        result = await self.fetch_page_result(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            end=end,
            use_cache=use_cache,
            parallel=parallel,
            page_phase=page_phase,
            page_priority=page_priority,
            page_timeout_seconds=page_timeout_seconds,
            page_max_retries=page_max_retries,
        )
        return result.items

    async def _fetch_page_result_for_position_lookup(  # noqa: PLR0913
        self,
        game: HeadlessGame,
        *,
        key: int,
        sub_key: int,
        start: int,
        end: int,
        use_cache: bool = False,
        parallel: bool = False,
        page_phase: str = "cached_anchor",
        page_priority: PlayerRankPagePriority = PlayerRankPagePriority.CACHED_ANCHOR,
        page_timeout_seconds: float | None = None,
        page_max_retries: int | None = None,
    ) -> RankPageResult:
        """Fetch one position-anchor page through the public page boundary.

        A cached rank position is only an anchor.  Confirmation deliberately
        reads that page again so the player can move within its 100-place band
        without becoming a false cache hit.  Calling ``fetch_page`` here also
        keeps the lookup compatible with the normal page cache and testable
        through the established page-fetch seam.
        """

        _ = use_cache
        page_kwargs: dict[str, Any] = {
            "key": key,
            "sub_key": sub_key,
            "start": start,
            "end": end,
            "use_cache": False,
        }
        if parallel:
            page_kwargs["parallel"] = True
        page_kwargs["page_phase"] = page_phase
        page_kwargs["page_priority"] = page_priority
        page_kwargs["page_timeout_seconds"] = page_timeout_seconds
        page_kwargs["page_max_retries"] = page_max_retries
        items = await self.fetch_page(game, **page_kwargs)
        return RankPageResult(items, time.time(), from_cache=False)

    async def fetch_item(  # noqa: PLR0913
        self,
        game: HeadlessGame,
        *,
        key: int,
        sub_key: int,
        index: int,
        use_cache: bool = False,
        parallel: bool = False,
        page_phase: str = "search",
        page_priority: PlayerRankPagePriority = PlayerRankPagePriority.SEARCH,
    ) -> Any | None:
        if use_cache:
            cached = self.cache.item_by_index(
                key=key,
                sub_key=sub_key,
                rank_index=index,
            )
            if cached is not None:
                observe_rank_page(
                    self.exclusion_policy,
                    key=key,
                    sub_key=sub_key,
                    start=index,
                    end=index,
                    items=[cached],
                    fetched_at=cached.fetched_at,
                    cached=True,
                )
                return cached
        page_size = self.page_size()
        page_start = self.page_start(index)
        items = await self.fetch_page(
            game,
            key=key,
            sub_key=sub_key,
            start=page_start,
            end=page_start + page_size - 1,
            use_cache=use_cache,
            parallel=parallel,
            page_phase=page_phase,
            page_priority=page_priority,
        )
        offset = index - page_start
        return items[offset] if 0 <= offset < len(items) else None

    def rank_probe_parallelism(self, game: HeadlessGame) -> int:
        """Return the spare public-pool capacity available to one search batch."""

        idle_workers = getattr(game, "idle_worker_count", None)
        if not isinstance(idle_workers, int):
            return 1
        return max(1, idle_workers)

    async def fetch_page_batch(  # noqa: PLR0913
        self,
        game: HeadlessGame,
        *,
        key: int,
        sub_key: int,
        starts: Sequence[int],
        use_cache: bool = False,
        page_phase: str = "search",
        page_priority: PlayerRankPagePriority = PlayerRankPagePriority.SEARCH,
    ) -> list[RankPageResult]:
        page_size = self.page_size()
        normalized_starts = tuple(dict.fromkeys(max(0, start) for start in starts))

        async def fetch_parallel_page(start: int) -> RankPageResult:
            token = _PARALLEL_RANK_PAGE_REQUEST.set(True)
            try:
                items = await self.fetch_page(
                    game,
                    key=key,
                    sub_key=sub_key,
                    start=start,
                    end=start + page_size - 1,
                    use_cache=use_cache,
                    page_phase=page_phase,
                    page_priority=page_priority,
                )
            finally:
                _PARALLEL_RANK_PAGE_REQUEST.reset(token)
            return RankPageResult(items, time.time(), from_cache=False)

        return list(
            await asyncio.gather(
                *(fetch_parallel_page(start) for start in normalized_starts)
            )
        )

    async def fetch_item_batch(  # noqa: PLR0913
        self,
        game: HeadlessGame,
        *,
        key: int,
        sub_key: int,
        indexes: Sequence[int],
        use_cache: bool = False,
        page_phase: str = "search",
        page_priority: PlayerRankPagePriority = PlayerRankPagePriority.SEARCH,
    ) -> list[Any | None]:
        page_starts = tuple(
            dict.fromkeys(self.page_start(index) for index in indexes if index >= 0)
        )
        pages = await self.fetch_page_batch(
            game,
            key=key,
            sub_key=sub_key,
            starts=page_starts,
            use_cache=use_cache,
            page_phase=page_phase,
            page_priority=page_priority,
        )
        items_by_page = dict(zip(page_starts, pages, strict=True))
        resolved: list[Any | None] = []
        for index in indexes:
            if index < 0:
                resolved.append(None)
                continue
            page_start = self.page_start(index)
            page = items_by_page[page_start]
            offset = index - page_start
            resolved.append(page.items[offset] if offset < len(page.items) else None)
        return resolved

    async def fetch_range(  # noqa: PLR0913
        self,
        game: HeadlessGame,
        *,
        key: int,
        sub_key: int,
        start: int,
        count: int,
        use_cache: bool = False,
    ) -> list[Any]:
        return await fetch_rank_range(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            count=count,
            use_cache=use_cache,
            rank_page_size=self.page_size,
            fetch_rank_page_result=self.fetch_page_result,
        )

    async def fetch_range_result(  # noqa: PLR0913
        self,
        game: HeadlessGame,
        *,
        key: int,
        sub_key: int,
        start: int,
        count: int,
        use_cache: bool = False,
    ) -> RankPageResult:
        return await fetch_rank_range_result(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            count=count,
            use_cache=use_cache,
            rank_page_size=self.page_size,
            fetch_rank_page_result=self.fetch_page_result,
        )

    @diagnose_rank_query
    async def fetch_visible_range_result(  # noqa: PLR0913
        self,
        game: HeadlessGame,
        *,
        rank_key: str,
        key: int,
        sub_key: int,
        start_rank: int,
        count: int,
    ) -> RankPageResult:
        return await fetch_visible_rank_range(
            self,
            game,
            rank_key=rank_key,
            key=key,
            sub_key=sub_key,
            start_rank=start_rank,
            count=count,
        )
