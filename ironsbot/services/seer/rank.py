# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Protocol

from ironsbot.services.seer import rank_summary
from ironsbot.services.seer.rank_cache_service import RankCacheQueryMixin
from ironsbot.services.seer.rank_constants import (
    AUTOCARD_RANK_KEY,
    AUTOCARD_RANK_SUB_KEY,
    PET_KIND_RANK_KEY,
    PET_KIND_RANK_SUB_KEY,
)
from ironsbot.services.seer.rank_exclusion_lookups import (
    fetch_visible_rank_range,
)
from ironsbot.services.seer.rank_exclusions import RankExclusionPolicy
from ironsbot.services.seer.rank_list_models import GLOBAL_RANKS, GlobalRankSpec
from ironsbot.services.seer.rank_live_lookup import execute_rank_lookup
from ironsbot.services.seer.rank_models import RankLookupResult, RankPageResult
from ironsbot.services.seer.rank_pagination import (
    rank_page_size as configured_page_size,
)
from ironsbot.services.seer.rank_pagination import (
    rank_page_start as configured_page_start,
)
from ironsbot.services.seer.rank_peak import datetime_to_sub_key
from ironsbot.services.seer.rank_player_scheduler import (
    PlayerRankLookupJob,
    PlayerRankPagePriority,
    current_player_rank_page_scheduler,
    run_player_rank_lookup_jobs,
)
from ironsbot.services.seer.rank_range import (
    fetch_rank_range,
    fetch_rank_range_result,
)
from ironsbot.services.seer.rank_score_search import (
    score_search_probe_limit,
    score_search_tie_page_limit,
)
from ironsbot.services.seer.rank_score_segments import fetch_score_segment_for_service
from ironsbot.services.seer.rank_work_cache import (
    cached_rank_miss,
    record_rank_page_work,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from datetime import datetime

    from ironsbot.config.models.seer import RankQueryConfig
    from ironsbot.services.operations.headless import HeadlessGame
    from ironsbot.services.seer.rank_models import (
        PeakSeasonRankSummary,
        PlayerRankSummary,
        RankEntry,
        RankScoreSearchResult,
        RankSummaryProgress,
    )
    from ironsbot.services.seer.rank_page_cache_models import (
        CachedRankLookup,
        CachedRankMiss,
        CachedRankPage,
        CachedRankPageSummary,
    )

_BOOK_BREAKDOWN_SCAN_LIMIT = 2_000
_LAST_CONFIRMED_RANK_MAX_AGE_SECONDS = 24 * 60 * 60
_PARALLEL_RANK_PAGE_REQUEST: ContextVar[bool] = ContextVar(
    "parallel_rank_page_request",
    default=False,
)
_LOGGER = logging.getLogger("ironsbot.seer.rank")


class RankPageCache(Protocol):
    def page(
        self,
        *,
        key: int,
        sub_key: int,
        start: int,
        end: int,
        allow_stale: bool | None = None,
    ) -> CachedRankPage | None: ...

    def item(
        self,
        *,
        key: int,
        sub_key: int,
        user_id: int,
        allow_stale: bool | None = None,
    ) -> CachedRankLookup | None: ...

    def item_by_index(
        self,
        *,
        key: int,
        sub_key: int,
        rank_index: int,
        allow_stale: bool | None = None,
    ) -> CachedRankLookup | None: ...

    def last_seen_item(
        self,
        *,
        key: int,
        sub_key: int,
        user_id: int,
        max_age_seconds: float,
    ) -> CachedRankLookup | None: ...

    def miss(
        self,
        *,
        key: int,
        sub_key: int,
        user_id: int,
        minimum_limit: int,
        allow_stale: bool | None = None,
    ) -> CachedRankMiss | None: ...

    def summary(self, *, key: int, sub_key: int) -> list[CachedRankPageSummary]: ...

    def score_indexes(
        self,
        *,
        key: int,
        sub_key: int,
        score: int,
        start_index: int,
        end_index: int,
    ) -> list[int]: ...

    def save(  # noqa: PLR0913
        self,
        *,
        key: int,
        sub_key: int,
        start: int,
        end: int,
        items: Sequence[object],
        fetched_at: float | None = None,
    ) -> None: ...

    def save_miss(
        self,
        *,
        key: int,
        sub_key: int,
        user_id: int,
        searched_limit: int,
        fetched_at: float | None = None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class RankService(RankCacheQueryMixin):
    config: RankQueryConfig
    cache: RankPageCache
    peak_season_start: Callable[[], datetime | None]
    fetch_online_page: Callable[..., Awaitable[list[RankEntry]]]
    exclusions: RankExclusionPolicy | None = field(default=None)

    def __post_init__(self) -> None:
        if self.exclusions is None:
            object.__setattr__(
                self,
                "exclusions",
                RankExclusionPolicy.from_config(self.config.exclusions),
            )

    @property
    def exclusion_policy(self) -> RankExclusionPolicy:
        assert self.exclusions is not None
        return self.exclusions

    def page_size(self) -> int:
        return configured_page_size(self.config.page_size)

    def page_start(self, index: int) -> int:
        return configured_page_start(index, page_size=self.page_size())

    def current_peak_sub_key(self) -> int | None:
        if self.config.peak_subkey is not None:
            return self.config.peak_subkey
        start = self.peak_season_start()
        return None if start is None else datetime_to_sub_key(start)

    def resolve_spec(self, spec: GlobalRankSpec) -> GlobalRankSpec:
        if not spec.peak_season_sub_key:
            return spec
        sub_key = self.current_peak_sub_key()
        return spec if sub_key is None else replace(spec, sub_key=sub_key)

    def get_spec(self, rank_key: str) -> GlobalRankSpec:
        return self.resolve_spec(GLOBAL_RANKS[rank_key])

    @staticmethod
    def spec_needs_sub_key(spec: GlobalRankSpec) -> bool:
        return spec.peak_season_sub_key and spec.sub_key <= 0

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

        async def fetch_online() -> list[RankEntry]:
            return await self.fetch_online_page(
                game,
                key=key,
                sub_key=sub_key,
                start=start,
                end=end,
            )

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
                "player rank page result: phase=%s key=%s sub_key=%s "
                "page=%s-%s worker=%s elapsed=%.3fs error=%s",
                page_phase,
                key,
                sub_key,
                start + 1,
                end + 1,
                getattr(game, "user_id", None),
                time.monotonic() - started_at,
                type(error).__name__,
            )
            raise
        _LOGGER.info(
            "player rank page result: phase=%s key=%s sub_key=%s "
            "page=%s-%s worker=%s elapsed=%.3fs items=%s",
            page_phase,
            key,
            sub_key,
            start + 1,
            end + 1,
            getattr(game, "user_id", None),
            time.monotonic() - started_at,
            len(items),
        )
        fetched_at = time.time()
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

    async def find_rank(  # noqa: PLR0913
        self,
        game: HeadlessGame,
        *,
        user_id: int,
        title: str,
        score_name: str,
        key: int,
        sub_key: int,
        target_score: int | None = None,
        search_limit: int | None = None,
        anchor_only: bool = False,
    ) -> RankLookupResult:
        rank_key = self.exclusion_policy.rank_key_for_protocol(
            key=key,
            sub_key=sub_key,
        )
        score_target = (
            target_score if target_score is not None and target_score > 0 else None
        )
        limit = (
            self._score_search_limit(rank_key, search_limit)
            if score_target is not None
            else self._online_search_limit(rank_key, search_limit)
        )
        page_size = self.page_size()
        result = RankLookupResult(
            title=title,
            score_name=score_name,
            searched_limit=limit,
            queried=limit > 0,
        )
        if self.exclusion_policy.excludes_from_public_rank(rank_key, user_id):
            result.excluded = True
            result.score = score_target
            return result
        fallback_item = self.cache.last_seen_item(
            key=key,
            sub_key=sub_key,
            user_id=user_id,
            max_age_seconds=_LAST_CONFIRMED_RANK_MAX_AGE_SECONDS,
        )
        if (
            score_target is None
            and (
                cached_miss := cached_rank_miss(
                    self.cache,
                    key=key,
                    sub_key=sub_key,
                    user_id=user_id,
                    minimum_limit=limit,
                )
            )
            is not None
        ):
            result.searched_limit = cached_miss.searched_limit
            result.cost.cache_page_hits += 1
            return result
        return await execute_rank_lookup(
            self,
            game,
            user_id=user_id,
            rank_key=rank_key,
            key=key,
            sub_key=sub_key,
            score_target=score_target,
            limit=limit,
            page_size=page_size,
            result=result,
            anchor_only=anchor_only,
            fallback_item=fallback_item,
        )

    async def find_pet_kind_rank(
        self,
        game: HeadlessGame,
        *,
        user_id: int,
        pet_kind_count: int,
        search_limit: int | None,
        anchor_only: bool = False,
    ) -> RankLookupResult:
        result = await self.find_rank(
            game,
            user_id=user_id,
            title="精灵图鉴",
            score_name="精灵",
            key=PET_KIND_RANK_KEY,
            sub_key=PET_KIND_RANK_SUB_KEY,
            target_score=pet_kind_count or None,
            search_limit=search_limit,
            anchor_only=anchor_only,
        )
        if result.score is None and pet_kind_count > 0:
            result.score = pet_kind_count
        return result

    async def fetch_score_segment(  # noqa: PLR0913
        self,
        game: HeadlessGame,
        *,
        rank_key: str | None = None,
        key: int,
        sub_key: int,
        title: str,
        score_name: str,
        target_score: int,
        search_limit: int | None = None,
        start_index: int = 0,
        sample_limit: int | None = None,
        use_superuser_limit: bool = False,
    ) -> RankScoreSearchResult:
        return await fetch_score_segment_for_service(
            self,
            game,
            rank_key=rank_key,
            key=key,
            sub_key=sub_key,
            title=title,
            score_name=score_name,
            target_score=target_score,
            search_limit=search_limit,
            start_index=start_index,
            sample_limit=sample_limit,
            use_superuser_limit=use_superuser_limit,
        )

    async def fetch_peak_summary(  # noqa: PLR0913
        self,
        game: HeadlessGame,
        user_id: int,
        *,
        standard_score: int | None = None,
        wild_score: int | None = None,
        expert_score: int | None = None,
        progress: RankSummaryProgress | None = None,
        anchor_only: bool = False,
    ) -> PeakSeasonRankSummary:
        return await rank_summary.fetch_peak_season_rank_summary(
            game,
            user_id,
            standard_score=standard_score,
            wild_score=wild_score,
            expert_score=expert_score,
            current_peak_sub_key=self.current_peak_sub_key(),
            find_rank=self.find_rank,
            progress=progress,
            anchor_only=anchor_only,
            run_lookup_jobs=self.run_player_lookup_jobs,
        )

    async def fetch_autocard_summary(
        self,
        game: HeadlessGame,
        user_id: int,
        *,
        anchor_only: bool = False,
    ) -> RankLookupResult:
        jobs = [
            PlayerRankLookupJob(
                id="autocard",
                title="群星之巅榜",
                key=AUTOCARD_RANK_KEY,
                sub_key=AUTOCARD_RANK_SUB_KEY,
                user_id=user_id,
                target_score=None,
                operation=lambda: rank_summary.fetch_autocard_rank_summary(
                    game,
                    user_id,
                    find_rank=self.find_rank,
                    anchor_only=anchor_only,
                ),
            )
        ]
        return (await self.run_player_lookup_jobs(jobs))["autocard"]

    async def fetch_player_summary(  # noqa: PLR0913
        self,
        game: HeadlessGame,
        user_id: int,
        *,
        book_score: int | None = None,
        achieve_score: int | None = None,
        pet_kind_count: int = 0,
        skin_score: int | None = None,
        progress: RankSummaryProgress | None = None,
        anchor_only: bool = False,
    ) -> PlayerRankSummary:
        return await rank_summary.fetch_player_rank_summary(
            game,
            user_id,
            book_score=book_score,
            achieve_score=achieve_score,
            pet_kind_count=pet_kind_count,
            skin_score=skin_score,
            book_breakdown_limit=min(
                max(0, self.config.limit),
                _BOOK_BREAKDOWN_SCAN_LIMIT,
            ),
            find_rank=self.find_rank,
            find_pet_kind_rank=self.find_pet_kind_rank,
            progress=progress,
            anchor_only=anchor_only,
            run_lookup_jobs=self.run_player_lookup_jobs,
        )

    async def run_player_lookup_jobs(
        self,
        jobs: Sequence[PlayerRankLookupJob],
    ) -> dict[str, RankLookupResult]:
        prioritized_jobs = tuple(self._with_player_lookup_priority(job) for job in jobs)
        return await run_player_rank_lookup_jobs(
            prioritized_jobs,
            self.config.player_lookup,
        )

    def _with_player_lookup_priority(
        self,
        job: PlayerRankLookupJob,
    ) -> PlayerRankLookupJob:
        priority_group, priority_rank, priority_reason = self._player_lookup_priority(
            job
        )
        return replace(
            job,
            priority_group=priority_group,
            priority_rank=priority_rank,
            priority_reason=priority_reason,
        )

    def _player_lookup_priority(
        self,
        job: PlayerRankLookupJob,
    ) -> tuple[int, int, str]:
        cached = self.cache.item(
            key=job.key,
            sub_key=job.sub_key,
            user_id=job.user_id,
            allow_stale=True,
        )
        if cached is not None:
            cache_age_seconds = max(0.0, time.time() - cached.fetched_at)
            if cache_age_seconds > _LAST_CONFIRMED_RANK_MAX_AGE_SECONDS:
                cached = None
        if cached is not None:
            cache_age_seconds = max(0.0, time.time() - cached.fetched_at)
            recent = (
                cache_age_seconds
                <= self.config.player_lookup.recent_cache_max_age_seconds
            )
            return (
                0 if recent else 1,
                cached.rank_index,
                "近期缓存名次" if recent else "缓存名次",
            )
        if job.target_score is not None and job.target_score > 0:
            rank_key = self.exclusion_policy.rank_key_for_protocol(
                key=job.key,
                sub_key=job.sub_key,
            )
            indexes = self.cache.score_indexes(
                key=job.key,
                sub_key=job.sub_key,
                score=job.target_score,
                start_index=0,
                end_index=self._score_search_limit(rank_key),
            )
            if indexes:
                return 2, min(indexes), "缓存同分位置"
            return 3, 2**31 - 1, "已知分数"
        return 4, 2**31 - 1, "无分数线性查找"

    def _online_search_limit(
        self,
        rank_key: str | None,
        search_limit: int | None = None,
    ) -> int:
        configured = max(
            0,
            self.config.lookup_limits.get(rank_key, self.config.online_limit)
            if rank_key is not None
            else self.config.online_limit,
        )
        requested = configured if search_limit is None else max(0, search_limit)
        return min(requested, configured)

    def _score_search_limit(
        self,
        rank_key: str | None,
        search_limit: int | None = None,
        *,
        use_superuser_limit: bool = False,
    ) -> int:
        configured = max(
            0,
            self.config.lookup_limits.get(rank_key, self.config.limit)
            if rank_key is not None
            else self.config.limit,
        )
        if use_superuser_limit:
            configured *= self.config.superuser_score_limit_multiplier
        requested = configured if search_limit is None else max(0, search_limit)
        return min(requested, configured)

    def _probe_limit(self, limit: int) -> int:
        return score_search_probe_limit(self.config, limit)

    def _tie_page_limit(self) -> int:
        return score_search_tie_page_limit(self.config)
