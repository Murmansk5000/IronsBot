# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import time
from dataclasses import dataclass, replace
from functools import partial
from typing import TYPE_CHECKING, Any, Protocol

from ironsbot.services.seer import rank_summary
from ironsbot.services.seer.rank_constants import (
    PET_KIND_RANK_ANOMALY_COUNT,
    PET_KIND_RANK_KEY,
    PET_KIND_RANK_SUB_KEY,
    is_pet_kind_rank_anomaly_user,
)
from ironsbot.services.seer.rank_list_models import GLOBAL_RANKS, GlobalRankSpec
from ironsbot.services.seer.rank_models import RankLookupResult, RankPageResult
from ironsbot.services.seer.rank_pagination import (
    rank_page_size as configured_page_size,
)
from ironsbot.services.seer.rank_pagination import (
    rank_page_start as configured_page_start,
)
from ironsbot.services.seer.rank_pagination import (
    rank_window_page_starts,
)
from ironsbot.services.seer.rank_peak import datetime_to_sub_key
from ironsbot.services.seer.rank_position_cache import find_rank_by_cached_position
from ironsbot.services.seer.rank_range import (
    fetch_rank_range,
    fetch_rank_range_result,
)
from ironsbot.services.seer.rank_score_cache import (
    cached_score_candidate_page_starts,
    cached_score_miss_boundary,
    fetch_rank_score_segment_from_cached_candidates,
)
from ironsbot.services.seer.rank_score_helpers import score_miss_proof_from_page
from ironsbot.services.seer.rank_score_lookup import (
    find_rank_by_linear_scan,
    find_rank_by_score,
)
from ironsbot.services.seer.rank_score_search import (
    score_search_probe_limit,
    score_search_tie_page_limit,
)
from ironsbot.services.seer.rank_score_segments import (
    RankScoreSegmentDependencies,
)
from ironsbot.services.seer.rank_score_segments import (
    fetch_rank_score_segment as fetch_rank_score_segment_online,
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
        CachedRankPage,
        CachedRankPageSummary,
    )

_CACHED_LOOKUP_WINDOW_PAGES = 2
_BOOK_BREAKDOWN_SCAN_LIMIT = 2_000


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


@dataclass(frozen=True, slots=True)
class RankService:
    config: RankQueryConfig
    cache: RankPageCache
    peak_season_start: Callable[[], datetime | None]
    fetch_online_page: Callable[..., Awaitable[list[RankEntry]]]

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
    ) -> RankPageResult:
        if use_cache:
            cached = self.cache.page(
                key=key,
                sub_key=sub_key,
                start=start,
                end=end,
            )
            if cached is not None:
                return RankPageResult(
                    list(cached.items),
                    cached.fetched_at,
                    from_cache=True,
                )

        items = await self.fetch_online_page(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            end=end,
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
    ) -> list[Any]:
        result = await self.fetch_page_result(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            end=end,
            use_cache=use_cache,
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
    ) -> RankPageResult:
        """Fetch one position-anchor page through the public page boundary.

        A cached rank position is only an anchor.  Confirmation deliberately
        reads that page again so the player can move within its 100-place band
        without becoming a false cache hit.  Calling ``fetch_page`` here also
        keeps the lookup compatible with the normal page cache and testable
        through the established page-fetch seam.
        """

        _ = use_cache
        items = await self.fetch_page(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            end=end,
            use_cache=False,
        )
        return RankPageResult(items, time.time(), from_cache=False)

    async def fetch_item(
        self,
        game: HeadlessGame,
        *,
        key: int,
        sub_key: int,
        index: int,
        use_cache: bool = False,
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
        )
        offset = index - page_start
        return items[offset] if 0 <= offset < len(items) else None

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
        score_target = (
            target_score
            if target_score is not None and target_score > 0
            else None
        )
        limit = (
            self._score_search_limit(search_limit)
            if score_target is not None
            else self._online_search_limit(search_limit)
        )
        page_size = self.page_size()
        result = RankLookupResult(
            title=title,
            score_name=score_name,
            searched_limit=limit,
            queried=limit > 0,
        )
        cached = await find_rank_by_cached_position(
            game,
            user_id=user_id,
            key=key,
            sub_key=sub_key,
            page_size=page_size,
            result=result,
            get_cached_rank_item=partial(self.cache.item, allow_stale=True),
            rank_window_page_starts=partial(
                rank_window_page_starts,
                window_pages=_CACHED_LOOKUP_WINDOW_PAGES,
            ),
            fetch_rank_page=self._fetch_page_result_for_position_lookup,
            anchor_only=anchor_only,
        )
        if cached is not None or limit <= 0 or anchor_only:
            return cached or result
        if score_target is not None:
            result.cost.used_score_search = True
            return await find_rank_by_score(
                game,
                user_id=user_id,
                key=key,
                sub_key=sub_key,
                target_score=score_target,
                limit=limit,
                page_size=page_size,
                result=result,
                score_search_probe_limit=self._probe_limit,
                score_search_tie_page_limit=self._tie_page_limit,
                fetch_rank_item=self.fetch_item,
                fetch_rank_page=self.fetch_page,
            )
        result.cost.used_full_scan = True
        return await find_rank_by_linear_scan(
            game,
            user_id=user_id,
            key=key,
            sub_key=sub_key,
            limit=limit,
            page_size=page_size,
            result=result,
            fetch_rank_page=self.fetch_page,
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
        real_limit = (
            self._score_search_limit(search_limit)
            if pet_kind_count > 0
            else self._online_search_limit(search_limit)
        )
        raw_limit = real_limit + PET_KIND_RANK_ANOMALY_COUNT
        result = RankLookupResult(
            title="精灵图鉴",
            score_name="精灵",
            score=pet_kind_count or None,
            searched_limit=real_limit,
            queried=real_limit > 0,
        )
        if is_pet_kind_rank_anomaly_user(user_id):
            result.rank = 0
            result.score = result.score or 0
            return result

        page_size = self.page_size()
        cached = await find_rank_by_cached_position(
            game,
            user_id=user_id,
            key=PET_KIND_RANK_KEY,
            sub_key=PET_KIND_RANK_SUB_KEY,
            page_size=page_size,
            result=result,
            get_cached_rank_item=partial(self.cache.item, allow_stale=True),
            rank_window_page_starts=partial(
                rank_window_page_starts,
                window_pages=_CACHED_LOOKUP_WINDOW_PAGES,
            ),
            fetch_rank_page=self.fetch_page_result,
            anchor_only=anchor_only,
        )
        if cached is not None:
            cached.searched_limit = real_limit
            if cached.rank is not None:
                cached.rank = max(
                    0,
                    cached.rank - PET_KIND_RANK_ANOMALY_COUNT,
                )
            return cached
        if real_limit <= 0 or anchor_only:
            return result

        if pet_kind_count > 0:
            result.cost.used_score_search = True
            result = await find_rank_by_score(
                game,
                user_id=user_id,
                key=PET_KIND_RANK_KEY,
                sub_key=PET_KIND_RANK_SUB_KEY,
                target_score=pet_kind_count,
                limit=raw_limit,
                page_size=page_size,
                result=result,
                score_search_probe_limit=self._probe_limit,
                score_search_tie_page_limit=self._tie_page_limit,
                fetch_rank_item=self.fetch_item,
                fetch_rank_page=self.fetch_page,
            )
        else:
            result.cost.used_full_scan = True
            result = await find_rank_by_linear_scan(
                game,
                user_id=user_id,
                key=PET_KIND_RANK_KEY,
                sub_key=PET_KIND_RANK_SUB_KEY,
                limit=raw_limit,
                page_size=page_size,
                result=result,
                fetch_rank_page=self.fetch_page,
            )
        result.searched_limit = real_limit
        if result.rank is not None:
            result.rank = max(0, result.rank - PET_KIND_RANK_ANOMALY_COUNT)
        return result

    async def fetch_score_segment(  # noqa: PLR0913
        self,
        game: HeadlessGame,
        *,
        key: int,
        sub_key: int,
        title: str,
        score_name: str,
        target_score: int,
        search_limit: int | None = None,
        start_index: int = 0,
        rank_offset: int = 0,
        sample_limit: int | None = None,
    ) -> RankScoreSearchResult:
        dependencies = RankScoreSegmentDependencies(
            score_search_limit=self._score_search_limit,
            rank_page_size=self.page_size,
            rank_page_start=self.page_start,
            cached_score_miss_boundary=partial(
                cached_score_miss_boundary,
                get_cache_summary=self.cache.summary,
                get_cached_score_indexes=self.cache.score_indexes,
                get_cached_page_result=self.cache.page,
                score_miss_proof_from_page=score_miss_proof_from_page,
            ),
            cached_score_candidate_page_starts=partial(
                cached_score_candidate_page_starts,
                rank_page_start=self.page_start,
                get_cached_score_indexes=self.cache.score_indexes,
                get_cache_summary=self.cache.summary,
            ),
            fetch_cached_candidates=partial(
                fetch_rank_score_segment_from_cached_candidates,
                rank_page_size=self.page_size,
                rank_page_start=self.page_start,
                score_search_tie_page_limit=self._tie_page_limit,
                fetch_rank_page_result=self.fetch_page_result,
            ),
            score_search_probe_limit=self._probe_limit,
            score_search_tie_page_limit=self._tie_page_limit,
            fetch_rank_item=self.fetch_item,
            fetch_rank_page_result=self.fetch_page_result,
            score_miss_proof_from_page=score_miss_proof_from_page,
        )
        return await fetch_rank_score_segment_online(
            game,
            key=key,
            sub_key=sub_key,
            title=title,
            score_name=score_name,
            target_score=target_score,
            search_limit=search_limit,
            start_index=start_index,
            rank_offset=rank_offset,
            sample_limit=sample_limit,
            deps=dependencies,
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
        )

    async def fetch_autocard_summary(
        self,
        game: HeadlessGame,
        user_id: int,
        *,
        anchor_only: bool = False,
    ) -> RankLookupResult:
        return await rank_summary.fetch_autocard_rank_summary(
            game,
            user_id,
            find_rank=self.find_rank,
            anchor_only=anchor_only,
        )

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
        )

    def _online_search_limit(self, search_limit: int | None = None) -> int:
        requested = (
            max(0, self.config.limit)
            if search_limit is None
            else max(0, search_limit)
        )
        return min(requested, max(0, self.config.online_limit))

    def _score_search_limit(self, search_limit: int | None = None) -> int:
        configured = max(0, self.config.limit)
        requested = configured if search_limit is None else max(0, search_limit)
        return min(requested, configured)

    def _probe_limit(self, limit: int) -> int:
        return score_search_probe_limit(self.config, limit)

    def _tie_page_limit(self) -> int:
        return score_search_tie_page_limit(self.config)
