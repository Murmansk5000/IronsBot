# SPDX-License-Identifier: GPL-3.0-or-later
"""Cache-only leaderboard entry points shared by the rank service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from ironsbot.services.seer.rank_cache_queries import (
    cached_player_lookup,
    fetch_cached_score_segment,
    fetch_cached_visible_rank_range,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.rank_exclusions import RankExclusionPolicy
    from ironsbot.services.seer.rank_models import (
        RankLookupResult,
        RankPageResult,
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
    ) -> RankPageResult | None:
        """Read a complete visible window from cache without a game session."""

        return fetch_cached_visible_rank_range(
            self.cache,
            key=key,
            sub_key=sub_key,
            start_rank=start_rank,
            count=count,
            page_size=self.page_size(),
            excluded_user_ids=self.exclusion_policy.excluded_user_ids(rank_key),
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

        return fetch_cached_score_segment(
            self.cache,
            key=key,
            sub_key=sub_key,
            title=title,
            score_name=score_name,
            target_score=target_score,
            search_limit=self._score_search_limit(rank_key, search_limit),
            start_index=start_index,
            sample_limit=sample_limit,
            page_size=self.page_size(),
            page_start=self.page_start,
            tie_page_limit=self._tie_page_limit(),
            excluded_user_ids=(
                frozenset()
                if rank_key is None
                else self.exclusion_policy.excluded_user_ids(rank_key)
            ),
        )

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

        if self.exclusion_policy.excludes_from_public_rank(rank_key, user_id):
            return None
        limit = (
            self._score_search_limit(rank_key, search_limit)
            if target_score is not None and target_score > 0
            else self._online_search_limit(rank_key, search_limit)
        )
        return cached_player_lookup(
            self.cache,
            key=key,
            sub_key=sub_key,
            user_id=user_id,
            title=title,
            score_name=score_name,
            search_limit=limit,
        )
