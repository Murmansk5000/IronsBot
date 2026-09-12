# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ironsbot.services.seer.rank_models import (
    RankPageResult,
    RankScoreGap,
    RankScoreMissProof,
    RankScoreSearchItem,
)
from ironsbot.services.seer.rank_pagination import (
    RankPageConflictError,
    RankPageSequence,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.services.seer.rank_score_search import DescendingScoreRange


def validate_score_sample(  # noqa: PLR0913
    page: RankPageResult,
    *,
    start: int,
    end: int,
    target_score: int,
    score_range: DescendingScoreRange,
    sequence: RankPageSequence,
) -> None:
    """Check sampled rows against proved bounds, not a speculative fallback end."""
    sequence.include((int(item.id), int(item.score)) for item in page.items)
    left, right = score_range.match_start, score_range.match_end
    if left is None or right is None:
        raise RankPageConflictError
    required_end = min(end + 1, left + 1 if score_range.truncated else right)
    if required_end > max(start, left) and start + len(page.items) < required_end:
        raise RankPageConflictError
    for offset, item in enumerate(page.items):
        index, score = start + offset, int(item.score)
        if (
            (index < left and score <= target_score)
            or (left <= index < required_end and score != target_score)
            or (not score_range.truncated and index >= right and score >= target_score)
        ):
            raise RankPageConflictError


@dataclass(frozen=True, slots=True)
class ScoreSegmentCoverage:
    matches: tuple[int, ...]
    missing_pages: tuple[int, ...]


def score_segment_coverage(
    pages: Mapping[int, RankPageResult],
    *,
    start_index: int,
    end_index: int,
    page_size: int,
    target_score: int,
) -> ScoreSegmentCoverage | None:
    """Plan pages proving a contiguous tie and its immediate score boundaries."""
    if page_size <= 0 or end_index <= start_index:
        return None
    if any(
        start < 0 or start % page_size or len(page.items) > page_size
        for start, page in pages.items()
    ):
        return None
    observed_end = min(
        [
            end_index,
            *(
                start + len(page.items)
                for start, page in pages.items()
                if len(page.items) < page_size
            ),
        ]
    )
    entries = sorted(
        (start + offset, int(item.id), int(item.score))
        for start, page in pages.items()
        for offset, item in enumerate(page.items)
        if start_index <= start + offset < end_index
    )
    if any(index >= observed_end for index, _, _ in entries):
        return None
    try:
        RankPageSequence().include((user_id, score) for _, user_id, score in entries)
    except RankPageConflictError:
        return None
    matches = tuple(index for index, _, score in entries if score == target_score)
    if not matches:
        return None

    # One observed neighbor at each open edge closes the tie; interior pages
    # must also exist before disconnected hints can become a population count.
    first_required = max(start_index, matches[0] - 1) // page_size * page_size
    last_required = min(observed_end - 1, matches[-1] + 1) // page_size * page_size
    missing = tuple(
        start
        for start in range(first_required, last_required + 1, page_size)
        if start not in pages
    )
    return ScoreSegmentCoverage(matches, missing)


def rank_score_search_item(item: Any, rank_index: int) -> RankScoreSearchItem:
    return RankScoreSearchItem(
        id=int(item.id),
        nick=str(item.nick),
        score=int(item.score),
        rank_index=rank_index,
    )


def score_segment_sample_indexes(
    start_index: int,
    end_index: int,
    display_limit: int | None,
) -> set[int] | None:
    """Return bounded head/tail indexes, or ``None`` when all items are needed."""
    total_count = max(0, end_index - start_index)
    if display_limit is None or total_count <= max(1, display_limit):
        return None
    if display_limit <= 1:
        return {start_index}

    side_count = display_limit // 2
    return {
        *range(start_index, start_index + side_count),
        *range(end_index - side_count, end_index),
    }


def score_gap_from_page(
    *,
    items: list[Any],
    page_start: int,
    score: int,
) -> RankScoreGap | None:
    matching_items = [
        rank_score_search_item(item, page_start + offset)
        for offset, item in enumerate(items)
        if int(item.score) == score
    ]
    if not matching_items:
        return None

    first_index = matching_items[0].rank_index
    last_index = matching_items[-1].rank_index
    page_end = page_start + len(items) - 1
    return RankScoreGap(
        score=score,
        start_rank=first_index + 1,
        end_rank=last_index + 1,
        total_count=len(matching_items),
        truncated=first_index == page_start or last_index == page_end,
        items=matching_items,
    )


def score_miss_proof_from_page(
    *,
    items: list[Any],
    page_start: int,
    target_score: int,
    fetched_at: float,
) -> RankScoreMissProof | None:
    if not items:
        return None

    lower_offset = next(
        (
            offset
            for offset, item in enumerate(items)
            if int(item.score) < target_score
        ),
        None,
    )
    if lower_offset is None or lower_offset <= 0:
        return None

    higher_score = int(items[lower_offset - 1].score)
    lower_score = int(items[lower_offset].score)
    if not higher_score > target_score > lower_score:
        return None

    return RankScoreMissProof(
        boundary_score=lower_score,
        fetched_at=fetched_at,
        higher_gap=score_gap_from_page(
            items=items,
            page_start=page_start,
            score=higher_score,
        ),
        lower_gap=score_gap_from_page(
            items=items,
            page_start=page_start,
            score=lower_score,
        ),
    )
