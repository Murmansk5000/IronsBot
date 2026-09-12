import pytest

from ironsbot.services.seer.rank_pagination import (
    RankPageConflictError,
    RankPageSequence,
    rank_page_size,
    rank_page_start,
    rank_window_page_starts,
)

MIN_PAGE_SIZE = 1
MID_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100


@pytest.mark.parametrize("following", [[(1, 8)], [(3, 11)], [(3, 8), (3, 7)]])
def test_sequence_rejects_duplicates_and_score_inversions(
    following: list[tuple[int, int]],
) -> None:
    sequence = RankPageSequence()
    sequence.include([(1, 10), (2, 9)])
    with pytest.raises(RankPageConflictError):
        sequence.include(following)


def test_sequence_accepts_ties_and_empty_terminal_page() -> None:
    sequence = RankPageSequence()
    sequence.include([(1, 10), (2, 9)])
    sequence.include([(3, 9), (4, 0)])
    sequence.include([])


def test_rank_page_size_clamps_protocol_limit() -> None:
    assert rank_page_size(0) == MIN_PAGE_SIZE
    assert rank_page_size(MID_PAGE_SIZE) == MID_PAGE_SIZE
    assert rank_page_size(500) == MAX_PAGE_SIZE


def test_rank_page_start_aligns_to_page_size() -> None:
    assert rank_page_start(-10, page_size=MAX_PAGE_SIZE) == 0
    assert rank_page_start(0, page_size=MAX_PAGE_SIZE) == 0
    assert rank_page_start(199, page_size=MAX_PAGE_SIZE) == MAX_PAGE_SIZE


def test_rank_window_page_starts_checks_anchor_page_before_expanding() -> None:
    assert rank_window_page_starts(
        center_index=250,
        page_size=MAX_PAGE_SIZE,
        window_pages=2,
    ) == [200, 100, 300, 0, 400]
