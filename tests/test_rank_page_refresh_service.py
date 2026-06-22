import time
from types import SimpleNamespace

from ironsbot.config.models.seer import RankPageRefreshConfig
from ironsbot.services.seer.rank_list import GlobalRankSpec
from ironsbot.services.seer.rank_page_refresh import (
    REFRESH_REASON_MISSING,
    REFRESH_REASON_PARTIAL,
    REFRESH_REASON_STALE,
    filter_standard_rank_page_summaries,
    select_rank_page_refresh_targets,
)


def test_select_rank_page_refresh_targets_prefers_first_missing_gap() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    config = RankPageRefreshConfig(target_limit=500, page_size=100, pages_per_run=2)
    pages = [
        SimpleNamespace(
            start_index=0,
            end_index=99,
            item_count=100,
            expected_count=100,
            fetched_at=time.time(),
            is_partial=False,
        ),
        SimpleNamespace(
            start_index=200,
            end_index=299,
            item_count=100,
            expected_count=100,
            fetched_at=time.time(),
            is_partial=False,
        ),
    ]

    targets = select_rank_page_refresh_targets(
        [("测试", spec)],
        {"测试": pages},
        config=config,
    )

    actual = [(target.reason, target.start_rank, target.end_rank) for target in targets]
    assert actual == [
        (REFRESH_REASON_MISSING, 101, 200),
        (REFRESH_REASON_MISSING, 301, 400),
    ]


def test_select_rank_page_refresh_targets_prefers_partial_before_stale() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    config = RankPageRefreshConfig(
        target_limit=200,
        page_size=100,
        pages_per_run=1,
        refresh_stale_after_hours=24,
    )
    pages = [
        SimpleNamespace(
            start_index=0,
            end_index=99,
            item_count=99,
            expected_count=100,
            fetched_at=time.time() - 48 * 3600,
            is_partial=True,
        ),
        SimpleNamespace(
            start_index=100,
            end_index=199,
            item_count=100,
            expected_count=100,
            fetched_at=time.time() - 48 * 3600,
            is_partial=False,
        ),
    ]

    targets = select_rank_page_refresh_targets(
        [("测试", spec)],
        {"测试": pages},
        config=config,
    )

    actual = [(target.reason, target.start_rank, target.end_rank) for target in targets]
    assert actual == [
        (REFRESH_REASON_PARTIAL, 1, 100)
    ]


def test_select_rank_page_refresh_targets_uses_stale_after_complete_pages() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    config = RankPageRefreshConfig(
        target_limit=200,
        page_size=100,
        pages_per_run=1,
        refresh_stale_after_hours=24,
    )
    pages = [
        SimpleNamespace(
            start_index=0,
            end_index=99,
            item_count=100,
            expected_count=100,
            fetched_at=time.time() - 48 * 3600,
            is_partial=False,
        ),
        SimpleNamespace(
            start_index=100,
            end_index=199,
            item_count=100,
            expected_count=100,
            fetched_at=time.time(),
            is_partial=False,
        ),
    ]

    targets = select_rank_page_refresh_targets(
        [("测试", spec)],
        {"测试": pages},
        config=config,
    )

    actual = [(target.reason, target.start_rank, target.end_rank) for target in targets]
    assert actual == [
        (REFRESH_REASON_STALE, 1, 100)
    ]


def test_filter_standard_rank_page_summaries_ignores_lookup_fragments() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    config = RankPageRefreshConfig(target_limit=300, page_size=100)
    pages = [
        SimpleNamespace(start_index=0, end_index=0),
        SimpleNamespace(start_index=0, end_index=99),
        SimpleNamespace(start_index=23, end_index=23),
        SimpleNamespace(start_index=100, end_index=199),
    ]

    filtered = filter_standard_rank_page_summaries(
        spec,
        pages,
        config=config,
    )

    assert [(page.start_index, page.end_index) for page in filtered] == [
        (0, 99),
        (100, 199),
    ]
