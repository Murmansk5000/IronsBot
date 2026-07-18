# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Protocol

from ironsbot.services.seer.rank_constants import is_pet_kind_rank_anomaly_user
from ironsbot.services.seer.rank_fetching import fetch_rank_page_result_from_game
from ironsbot.services.seer.rank_list_models import GLOBAL_RANKS, GlobalRankSpec
from ironsbot.services.seer.rank_lookup_service import (
    RankLookupDependencies,
)
from ironsbot.services.seer.rank_lookup_service import (
    find_pet_kind_rank as find_pet_kind_rank_with_deps,
)
from ironsbot.services.seer.rank_lookup_service import (
    find_rank as find_rank_with_deps,
)
from ironsbot.services.seer.rank_pagination import (
    rank_page_size as configured_page_size,
)
from ironsbot.services.seer.rank_pagination import (
    rank_page_start as configured_page_start,
)
from ironsbot.services.seer.rank_pagination import (
    rank_window_page_starts,
)
from ironsbot.services.seer.rank_peak import get_current_peak_sub_key
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
    fetch_rank_score_segment as fetch_rank_score_segment_online,
)
from ironsbot.services.seer.rank_score_service import (
    RankScoreServiceDependencies,
)
from ironsbot.services.seer.rank_score_service import (
    fetch_rank_score_segment as fetch_rank_score_segment_with_deps,
)
from ironsbot.services.seer.rank_summary import (
    fetch_autocard_rank_summary as fetch_autocard_rank_summary_with_deps,
)
from ironsbot.services.seer.rank_summary import (
    fetch_peak_season_rank_summary as fetch_peak_season_rank_summary_with_deps,
)
from ironsbot.services.seer.rank_summary import (
    fetch_player_rank_summary as fetch_player_rank_summary_with_deps,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ironsbot.config.models.seer import RankQueryConfig
    from ironsbot.integrations.headless_seer.game import SeerGame
    from ironsbot.services.seer.rank_models import (
        PeakSeasonRankSummary,
        PlayerRankSummary,
        RankLookupResult,
        RankPageResult,
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

    def page_size(self) -> int:
        return configured_page_size(self.config)

    def page_start(self, index: int) -> int:
        return configured_page_start(index, page_size=self.page_size())

    def current_peak_sub_key(self) -> int | None:
        return get_current_peak_sub_key(self.config.peak_subkey)

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
        game: SeerGame,
        *,
        key: int,
        sub_key: int,
        start: int,
        end: int,
        use_cache: bool = False,
    ) -> RankPageResult:
        return await fetch_rank_page_result_from_game(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            end=end,
            use_cache=use_cache,
            get_cached_page=self.cache.page,
            save_page=self.cache.save,
        )

    async def fetch_page(  # noqa: PLR0913
        self,
        game: SeerGame,
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

    async def fetch_item(
        self,
        game: SeerGame,
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
        game: SeerGame,
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
        game: SeerGame,
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
        game: SeerGame,
        *,
        user_id: int,
        title: str,
        score_name: str,
        key: int,
        sub_key: int,
        target_score: int | None = None,
        search_limit: int | None = None,
    ) -> RankLookupResult:
        return await find_rank_with_deps(
            game,
            user_id=user_id,
            title=title,
            score_name=score_name,
            key=key,
            sub_key=sub_key,
            target_score=target_score,
            search_limit=search_limit,
            deps=self._lookup_dependencies(),
        )

    async def find_pet_kind_rank(
        self,
        game: SeerGame,
        *,
        user_id: int,
        pet_kind_count: int,
        search_limit: int | None,
    ) -> RankLookupResult:
        return await find_pet_kind_rank_with_deps(
            game,
            user_id=user_id,
            pet_kind_count=pet_kind_count,
            search_limit=search_limit,
            deps=self._lookup_dependencies(),
        )

    async def fetch_score_segment(  # noqa: PLR0913
        self,
        game: SeerGame,
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
        return await fetch_rank_score_segment_with_deps(
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
            deps=self._score_dependencies(),
        )

    async def fetch_peak_summary(  # noqa: PLR0913
        self,
        game: SeerGame,
        user_id: int,
        *,
        standard_score: int | None = None,
        wild_score: int | None = None,
        expert_score: int | None = None,
        progress: RankSummaryProgress | None = None,
    ) -> PeakSeasonRankSummary:
        return await fetch_peak_season_rank_summary_with_deps(
            game,
            user_id,
            standard_score=standard_score,
            wild_score=wild_score,
            expert_score=expert_score,
            current_peak_sub_key=self.current_peak_sub_key(),
            find_rank=self.find_rank,
            progress=progress,
        )

    async def fetch_autocard_summary(
        self,
        game: SeerGame,
        user_id: int,
    ) -> RankLookupResult:
        return await fetch_autocard_rank_summary_with_deps(
            game,
            user_id,
            find_rank=self.find_rank,
        )

    async def fetch_player_summary(  # noqa: PLR0913
        self,
        game: SeerGame,
        user_id: int,
        *,
        book_score: int | None = None,
        achieve_score: int | None = None,
        pet_kind_count: int = 0,
        skin_score: int | None = None,
        progress: RankSummaryProgress | None = None,
    ) -> PlayerRankSummary:
        return await fetch_player_rank_summary_with_deps(
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

    def _window_page_starts(
        self,
        *,
        center_index: int,
        page_size: int,
    ) -> list[int]:
        return rank_window_page_starts(
            center_index=center_index,
            page_size=page_size,
            window_pages=_CACHED_LOOKUP_WINDOW_PAGES,
        )

    async def _find_by_cached_position(self, game: SeerGame, **kwargs: Any) -> Any:
        return await find_rank_by_cached_position(
            game,
            **kwargs,
            get_cached_rank_item=self.cache.item,
            rank_window_page_starts=self._window_page_starts,
            fetch_rank_page=self.fetch_page,
        )

    async def _find_by_score(self, game: SeerGame, **kwargs: Any) -> RankLookupResult:
        return await find_rank_by_score(
            game,
            **kwargs,
            score_search_probe_limit=self._probe_limit,
            score_search_tie_page_limit=self._tie_page_limit,
            fetch_rank_item=self.fetch_item,
            fetch_rank_page=self.fetch_page,
        )

    async def _find_by_linear_scan(
        self,
        game: SeerGame,
        **kwargs: Any,
    ) -> RankLookupResult:
        return await find_rank_by_linear_scan(
            game,
            **kwargs,
            fetch_rank_page=self.fetch_page,
        )

    def _lookup_dependencies(self) -> RankLookupDependencies:
        return RankLookupDependencies(
            online_search_limit=self._online_search_limit,
            score_search_limit=self._score_search_limit,
            page_size=self.page_size,
            is_pet_kind_rank_anomaly_user=is_pet_kind_rank_anomaly_user,
            find_rank_by_cached_position=self._find_by_cached_position,
            find_rank_by_score=self._find_by_score,
            find_rank_by_linear_scan=self._find_by_linear_scan,
        )

    def _score_dependencies(self) -> RankScoreServiceDependencies:
        return RankScoreServiceDependencies(
            rank_page_size=self.page_size,
            rank_page_start=self.page_start,
            score_search_limit=self._score_search_limit,
            score_search_probe_limit=self._probe_limit,
            score_search_tie_page_limit=self._tie_page_limit,
            get_cached_score_indexes=self.cache.score_indexes,
            get_cache_summary=self.cache.summary,
            get_cached_page_result=self.cache.page,
            score_miss_proof_from_page=score_miss_proof_from_page,
            fetch_cached_candidates_impl=fetch_rank_score_segment_from_cached_candidates,
            fetch_rank_score_segment_impl=fetch_rank_score_segment_online,
            cached_score_candidate_page_starts_impl=cached_score_candidate_page_starts,
            cached_score_miss_boundary_impl=cached_score_miss_boundary,
            fetch_rank_item=self.fetch_item,
            fetch_rank_page_result=self.fetch_page_result,
        )
