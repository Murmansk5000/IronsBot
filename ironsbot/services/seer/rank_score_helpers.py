# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Any

from ironsbot.services.seer.rank_models import (
    RankScoreGap,
    RankScoreMissProof,
    RankScoreSearchItem,
)


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
    rank_offset: int,
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
        start_rank=first_index + 1 + rank_offset,
        end_rank=last_index + 1 + rank_offset,
        total_count=len(matching_items),
        truncated=first_index == page_start or last_index == page_end,
        items=matching_items,
    )


def score_miss_proof_from_page(
    *,
    items: list[Any],
    page_start: int,
    target_score: int,
    rank_offset: int,
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
            rank_offset=rank_offset,
        ),
        lower_gap=score_gap_from_page(
            items=items,
            page_start=page_start,
            score=lower_score,
            rank_offset=rank_offset,
        ),
    )
