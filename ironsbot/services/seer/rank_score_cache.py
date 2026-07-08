# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Callable, Sequence
from typing import Any

from ironsbot.services.seer.rank_models import RankScoreMissProof


def cached_score_candidate_page_starts(  # noqa: PLR0913
    *,
    key: int,
    sub_key: int,
    target_score: int,
    start_index: int,
    end_index: int,
    rank_page_start: Callable[[int], int],
    get_cached_score_indexes: Callable[..., Sequence[int]],
    get_cache_summary: Callable[..., Sequence[Any]],
) -> list[int]:
    starts: list[int] = []
    starts.extend(
        rank_page_start(index)
        for index in get_cached_score_indexes(
            key=key,
            sub_key=sub_key,
            score=target_score,
            start_index=start_index,
            end_index=end_index,
        )
    )
    for page in get_cache_summary(key=key, sub_key=sub_key):
        if page.min_score is None or page.max_score is None:
            continue
        if page.end_index < start_index or page.start_index >= end_index:
            continue
        if int(page.min_score) <= target_score <= int(page.max_score):
            starts.append(rank_page_start(max(start_index, page.start_index)))
    return sorted(set(starts))


def cached_score_miss_boundary(  # noqa: PLR0913
    *,
    key: int,
    sub_key: int,
    target_score: int,
    start_index: int,
    end_index: int,
    rank_offset: int,
    get_cache_summary: Callable[..., Sequence[Any]],
    get_cached_score_indexes: Callable[..., Sequence[int]],
    get_cached_page_result: Callable[..., Any | None],
    score_miss_proof_from_page: Callable[..., RankScoreMissProof | None],
) -> RankScoreMissProof | None:
    for page in get_cache_summary(key=key, sub_key=sub_key):
        if getattr(page, "is_stale", False) or getattr(page, "is_partial", False):
            continue
        item_count = getattr(page, "item_count", None)
        expected_count = getattr(page, "expected_count", None)
        if (
            item_count is None
            or expected_count is None
            or int(item_count) <= 0
            or int(item_count) != int(expected_count)
        ):
            continue
        if page.min_score is None or page.max_score is None:
            continue
        if page.end_index < start_index or page.start_index >= end_index:
            continue
        if not int(page.min_score) <= target_score <= int(page.max_score):
            continue

        exact_indexes = get_cached_score_indexes(
            key=key,
            sub_key=sub_key,
            score=target_score,
            start_index=max(start_index, page.start_index),
            end_index=min(end_index, page.end_index + 1),
        )
        if exact_indexes:
            continue

        cached_page = get_cached_page_result(
            key=key,
            sub_key=sub_key,
            start=int(page.start_index),
            end=int(page.end_index),
            allow_stale=False,
        )
        if cached_page is None:
            return RankScoreMissProof(
                boundary_score=int(page.min_score),
                fetched_at=float(page.fetched_at),
            )
        return score_miss_proof_from_page(
            items=list(cached_page.items),
            page_start=int(page.start_index),
            target_score=target_score,
            rank_offset=rank_offset,
            fetched_at=cached_page.fetched_at,
        ) or RankScoreMissProof(
            boundary_score=int(page.min_score),
            fetched_at=float(page.fetched_at),
        )
    return None


__all__ = [
    "cached_score_candidate_page_starts",
    "cached_score_miss_boundary",
]
