from types import SimpleNamespace
from typing import cast

from ironsbot.config.models.seer import RankQueryConfig
from ironsbot.services.seer.rank_pagination import (
    rank_page_size,
    rank_page_start,
    rank_window_page_starts,
)

MIN_PAGE_SIZE = 1
MID_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100


def test_rank_page_size_clamps_protocol_limit() -> None:
    assert (
        rank_page_size(cast("RankQueryConfig", SimpleNamespace(page_size=0)))
        == MIN_PAGE_SIZE
    )
    assert rank_page_size(RankQueryConfig(page_size=MID_PAGE_SIZE)) == MID_PAGE_SIZE
    assert rank_page_size(RankQueryConfig(page_size=500)) == MAX_PAGE_SIZE


def test_rank_page_start_aligns_to_page_size() -> None:
    assert rank_page_start(-10, page_size=MAX_PAGE_SIZE) == 0
    assert rank_page_start(0, page_size=MAX_PAGE_SIZE) == 0
    assert rank_page_start(199, page_size=MAX_PAGE_SIZE) == MAX_PAGE_SIZE


def test_rank_window_page_starts_uses_symmetric_window() -> None:
    assert rank_window_page_starts(
        center_index=250,
        page_size=MAX_PAGE_SIZE,
        window_pages=2,
    ) == [0, 100, 200, 300, 400]
