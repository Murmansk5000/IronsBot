# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Awaitable, Callable

from ironsbot.config.models.seer import RankQueryConfig

DEFAULT_SCORE_SEARCH_PROBE_LIMIT = 32
DEFAULT_SCORE_SEARCH_TIE_PAGE_LIMIT = 5


class RankSearchBudgetExhaustedError(RuntimeError):
    pass


async def find_last_existing_score_index(
    start_index: int,
    end_index: int,
    score_at: Callable[[int], Awaitable[int | None]],
) -> tuple[int | None, int | None]:
    if end_index <= start_index:
        return None, None

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


def score_search_probe_limit(config: RankQueryConfig, limit: int) -> int:
    configured = int(
        getattr(config, "score_search_probe_limit", DEFAULT_SCORE_SEARCH_PROBE_LIMIT)
    )
    return max(1, min(configured, max(limit, 1)))


def score_search_tie_page_limit(config: RankQueryConfig) -> int:
    configured = int(
        getattr(
            config,
            "score_search_tie_page_limit",
            DEFAULT_SCORE_SEARCH_TIE_PAGE_LIMIT,
        )
    )
    return max(1, configured)


__all__ = [
    "DEFAULT_SCORE_SEARCH_PROBE_LIMIT",
    "DEFAULT_SCORE_SEARCH_TIE_PAGE_LIMIT",
    "RankSearchBudgetExhaustedError",
    "find_last_existing_score_index",
    "score_search_probe_limit",
    "score_search_tie_page_limit",
]

