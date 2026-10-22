# SPDX-License-Identifier: GPL-3.0-or-later
"""Cache-only leaderboard entry points shared by the rank service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from ironsbot.services.seer.rank_cache_queries import (
    cached_player_lookup,
    fetch_cached_score_segment,
)
from ironsbot.services.seer.rank_list_models import GLOBAL_RANKS
from ironsbot.services.seer.rank_visibility import (
    EXCLUSION_PREFIX_SIZE,
    uses_filtered_prefix,
)
from ironsbot.services.seer.rank_visibility_cache import CachedRankVisibility

if TYPE_CHECKING:
    from ironsbot.services.seer.rank_exclusions import RankExclusionPolicy
    from ironsbot.services.seer.rank_models import (
        RankLookupResult,
        RankRangeResult,
        RankScoreSearchResult,
    )
    from ironsbot.services.seer.rank_page_cache_models import CachedRankLookup


class _RankCacheQueryHost(Protocol):
    @property
    def cache(self) -> Any: ...

    @property
    def exclusion_policy(self) -> RankExclusionPolicy: ...

    def page_size(self) -> int: ...

    def page_start(self, index: int) -> int: ...

    def _score_search_limit(
        self,
        rank_key: str | None,
        search_limit: int | None = None,
    ) -> int: ...

    def _online_search_limit(
        self,
        rank_key: str | None,
        search_limit: int | None = None,
    ) -> int: ...

    def _tie_page_limit(self) -> int: ...


class RankCacheQueryMixin:
    """Expose cache-only reads without coupling callers to cache internals."""

    def cached_visible_range_result(
        self: _RankCacheQueryHost,
        *,
        rank_key: str,
        key: int,
        sub_key: int,
        start_rank: int,
        count: int,
    ) -> RankRangeResult | None:
        """Read a complete visible window from cache without a game session."""

        return CachedRankVisibility(
            self, rank_key=rank_key, key=key, sub_key=sub_key
        ).range(
            start_rank,
            count,
            ascending=(rank_key in GLOBAL_RANKS and GLOBAL_RANKS[rank_key].ascending),
        )

    def cached_score_segment(  # noqa: PLR0913
        self: _RankCacheQueryHost,
        *,
        rank_key: str | None,
        key: int,
        sub_key: int,
        title: str,
        score_name: str,
        target_score: int,
        search_limit: int | None = None,
        start_index: int = 0,
        sample_limit: int | None = None,
    ) -> RankScoreSearchResult | None:
        """Read a complete score segment from cache without a game session."""

        query = CachedRankVisibility(self, rank_key=rank_key, key=key, sub_key=sub_key)
        result = fetch_cached_score_segment(
            self.cache,
            key=key,
            sub_key=sub_key,
            title=title,
            score_name=score_name,
            target_score=target_score,
            search_limit=self._score_search_limit(rank_key, search_limit),
            start_index=start_index,
            sample_limit=None
            if rank_key is not None
            and self.exclusion_policy.excluded_user_ids(rank_key)
            else sample_limit,
            page_size=self.page_size(),
            page_start=self.page_start,
            tie_page_limit=self._tie_page_limit(),
            excluded_user_ids=frozenset(),
        )
        if result is None:
            return None
        last_rank = max(
            result.end_rank or 0,
            *(
                gap.end_rank if gap is not None else 0
                for gap in (result.higher_gap, result.lower_gap)
            ),
        )
        visibility = query.visibility(raw_until=last_rank)
        if visibility is None:
            return None
        query.observation.include(result.fetched_at)
        result.fetched_at = query.observation.fetched_at
        return visibility.apply_score_result(result)

    def cached_player_lookup(  # noqa: PLR0913
        self: _RankCacheQueryHost,
        *,
        rank_key: str,
        user_id: int,
        title: str,
        score_name: str,
        key: int,
        sub_key: int,
        target_score: int | None = None,
        search_limit: int | None = None,
    ) -> tuple[CachedRankLookup | None, RankLookupResult] | None:
        """Read a cached player rank or complete-miss result without login."""

        limit = (
            self._score_search_limit(rank_key, search_limit)
            if target_score is not None and target_score > 0
            else self._online_search_limit(rank_key, search_limit)
        )
        cached = cached_player_lookup(
            self.cache,
            key=key,
            sub_key=sub_key,
            user_id=user_id,
            title=title,
            score_name=score_name,
            search_limit=limit,
            allow_stale=not (
                uses_filtered_prefix(rank_key)
                and self.exclusion_policy.excluded_user_ids(rank_key)
            ),
        )
        if cached is None:
            return None
        item, result = cached
        if result.rank is None:
            return cached
        query = CachedRankVisibility(self, rank_key=rank_key, key=key, sub_key=sub_key)
        visibility = query.visibility(raw_until=result.rank)
        if visibility is None:
            return None
        if visibility.filtered_prefix and visibility.excluded_ids:
            if len(query.prefix) < min(result.rank, EXCLUSION_PREFIX_SIZE):
                return None
            if result.rank <= len(query.prefix):
                observed = query.prefix[result.rank - 1]
                if int(observed.id) != user_id or int(observed.score) != result.score:
                    return None
        if visibility.hides(result.rank - 1, user_id):
            result.excluded, result.rank = True, None
        else:
            result.rank = visibility.public_index(result.rank - 1) + 1
        if query.observation.fetched_at is not None:
            result.include_observation(query.observation.fetched_at)
        return item, result
