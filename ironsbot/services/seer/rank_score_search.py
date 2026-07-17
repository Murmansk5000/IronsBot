# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.config.models.seer import RankQueryConfig


DEFAULT_SCORE_SEARCH_PROBE_LIMIT = 32
DEFAULT_SCORE_SEARCH_TIE_PAGE_LIMIT = 5


class _ProbeBudgetExhaustedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DescendingScoreRange:
    last_index: int | None = None
    boundary_score: int | None = None
    insertion_index: int | None = None
    match_start: int | None = None
    match_end: int | None = None
    truncated: bool = False
    budget_exhausted: bool = False


@dataclass(frozen=True, slots=True)
class DescendingScoreSearchLimits:
    probe_count: int
    tie_fallback_size: int


class _ScoreProbe:
    def __init__(
        self,
        fetch_score: Callable[[int], Awaitable[int | None]],
        probe_count: int,
    ) -> None:
        self._fetch_score = fetch_score
        self._probe_count = max(0, probe_count)
        self._remaining = self._probe_count
        self._cache: dict[int, int | None] = {}

    def reset_budget(self) -> None:
        self._remaining = self._probe_count

    async def score_at(self, index: int) -> int | None:
        if index in self._cache:
            return self._cache[index]
        if self._remaining <= 0:
            raise _ProbeBudgetExhaustedError

        self._remaining -= 1
        score = await self._fetch_score(index)
        self._cache[index] = score
        return score


async def _find_last_existing_index(
    start_index: int,
    end_index: int,
    score_at: Callable[[int], Awaitable[int | None]],
) -> tuple[int | None, int | None]:
    boundary_index = end_index - 1
    boundary_score = await score_at(boundary_index)
    if boundary_score is not None:
        return boundary_index, boundary_score

    first_score = await score_at(start_index)
    if first_score is None:
        return None, None

    low = start_index
    high = boundary_index
    while low + 1 < high:
        mid = (low + high) // 2
        score = await score_at(mid)
        if score is None:
            high = mid
        else:
            low = mid

    return low, await score_at(low)


async def _find_first_at_most(
    start_index: int,
    end_index: int,
    target_score: int,
    score_at: Callable[[int], Awaitable[int | None]],
) -> int:
    low = start_index
    high = end_index
    while low < high:
        mid = (low + high) // 2
        score = await score_at(mid)
        if score is None or score <= target_score:
            high = mid
        else:
            low = mid + 1
    return low


async def _find_first_below(
    start_index: int,
    end_index: int,
    target_score: int,
    score_at: Callable[[int], Awaitable[int | None]],
) -> int:
    low = start_index
    high = end_index
    while low < high:
        mid = (low + high) // 2
        score = await score_at(mid)
        if score is None or score < target_score:
            high = mid
        else:
            low = mid + 1
    return low


async def _locate_matches(
    base_result: DescendingScoreRange,
    *,
    search_range: range,
    target_score: int,
    probe: _ScoreProbe,
    tie_fallback_size: int,
) -> DescendingScoreRange:
    try:
        insertion_index = await _find_first_at_most(
            search_range.start,
            search_range.stop,
            target_score,
            probe.score_at,
        )
        if insertion_index >= search_range.stop:
            return replace(base_result, insertion_index=insertion_index)
        first_score = await probe.score_at(insertion_index)
    except _ProbeBudgetExhaustedError:
        return replace(base_result, budget_exhausted=True)

    if first_score != target_score:
        return replace(base_result, insertion_index=insertion_index)

    probe.reset_budget()
    try:
        match_end = await _find_first_below(
            insertion_index,
            search_range.stop,
            target_score,
            probe.score_at,
        )
    except _ProbeBudgetExhaustedError:
        return replace(
            base_result,
            insertion_index=insertion_index,
            match_start=insertion_index,
            match_end=min(
                search_range.stop,
                insertion_index + max(0, tie_fallback_size),
            ),
            truncated=True,
            budget_exhausted=True,
        )

    return replace(
        base_result,
        insertion_index=insertion_index,
        match_start=insertion_index,
        match_end=match_end,
    )


async def locate_descending_score_range(
    start_index: int,
    end_index: int,
    target_score: int,
    fetch_score: Callable[[int], Awaitable[int | None]],
    *,
    limits: DescendingScoreSearchLimits,
) -> DescendingScoreRange:
    """Locate a score range in a descending leaderboard with bounded probes."""
    if end_index <= start_index:
        return DescendingScoreRange()

    probe = _ScoreProbe(fetch_score, limits.probe_count)

    try:
        last_index, boundary_score = await _find_last_existing_index(
            start_index,
            end_index,
            probe.score_at,
        )
    except _ProbeBudgetExhaustedError:
        return DescendingScoreRange(budget_exhausted=True)

    if last_index is None:
        return DescendingScoreRange()

    search_end = last_index + 1
    base_result = DescendingScoreRange(
        last_index=last_index,
        boundary_score=boundary_score,
    )
    if boundary_score is None or target_score < boundary_score:
        return base_result

    probe.reset_budget()
    return await _locate_matches(
        base_result,
        search_range=range(start_index, search_end),
        target_score=target_score,
        probe=probe,
        tie_fallback_size=limits.tie_fallback_size,
    )


def score_search_probe_limit(config: RankQueryConfig, limit: int) -> int:
    return max(1, min(config.score_search_probe_limit, max(limit, 1)))


def score_search_tie_page_limit(config: RankQueryConfig) -> int:
    return config.score_search_tie_page_limit


__all__ = [
    "DEFAULT_SCORE_SEARCH_PROBE_LIMIT",
    "DEFAULT_SCORE_SEARCH_TIE_PAGE_LIMIT",
    "DescendingScoreRange",
    "DescendingScoreSearchLimits",
    "locate_descending_score_range",
    "score_search_probe_limit",
    "score_search_tie_page_limit",
]
