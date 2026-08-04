import time

from ironsbot.config.models.seer import RankPageRefreshConfig
from ironsbot.services.seer.rank_list_models import GlobalRankSpec
from ironsbot.services.seer.rank_page_cache_models import CachedRankPageSummary
from ironsbot.services.seer.rank_page_refresh_selection import (
    REFRESH_REASON_MISSING,
    REFRESH_REASON_PARTIAL,
    REFRESH_REASON_STALE,
    filter_standard_rank_page_summaries,
    rank_refresh_target_label,
    rank_score_cutoff,
    rank_target_limit,
    select_rank_page_refresh_targets,
)

PER_RANK_TARGET_LIMIT = 200


def page_summary(  # noqa: PLR0913
    *,
    start_index: int,
    end_index: int,
    item_count: int = 100,
    expected_count: int = 100,
    fetched_at: float = 0.0,
    is_partial: bool = False,
    min_score: int | None = None,
) -> CachedRankPageSummary:
    return CachedRankPageSummary(
        start_index=start_index,
        end_index=end_index,
        item_count=item_count,
        expected_count=expected_count,
        fetched_at=fetched_at,
        is_partial=is_partial,
        min_score=min_score,
    )


TEST_SCORE_CUTOFF = 1000
TEST_SCORE_TARGET_LABEL = "分数 >= 1000（最多前 500 名）"


def test_select_rank_page_refresh_targets_prefers_first_missing_gap() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    config = RankPageRefreshConfig(target_limit=500, page_size=100, pages_per_run=2)
    pages = [
        page_summary(
            start_index=0,
            end_index=99,
            item_count=100,
            expected_count=100,
            fetched_at=time.time(),
            is_partial=False,
        ),
        page_summary(
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


def test_select_rank_page_refresh_targets_uses_partial_missing_ratio() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    config = RankPageRefreshConfig(
        target_limit=200,
        page_size=100,
        pages_per_run=1,
        refresh_stale_after_hours=24,
    )
    pages = [
        page_summary(
            start_index=0,
            end_index=99,
            item_count=99,
            expected_count=100,
            fetched_at=time.time() - 48 * 3600,
            is_partial=True,
        ),
        page_summary(
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
        (REFRESH_REASON_STALE, 101, 200)
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
        page_summary(
            start_index=0,
            end_index=99,
            item_count=100,
            expected_count=100,
            fetched_at=time.time() - 48 * 3600,
            is_partial=False,
        ),
        page_summary(
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


def test_select_rank_page_refresh_targets_prioritizes_front_pages_by_index() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    config = RankPageRefreshConfig(
        target_limit=500,
        page_size=100,
        pages_per_run=2,
        refresh_stale_after_hours=24,
    )
    pages = [
        page_summary(
            start_index=0,
            end_index=99,
            item_count=100,
            expected_count=100,
            fetched_at=time.time() - 48 * 3600,
            is_partial=False,
        ),
        page_summary(
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
        (REFRESH_REASON_STALE, 1, 100),
        (REFRESH_REASON_MISSING, 201, 300),
    ]


def test_select_rank_page_refresh_targets_uses_rank_position_page_index() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    config = RankPageRefreshConfig(
        target_limit=5000,
        page_size=100,
        pages_per_run=2,
        refresh_stale_after_hours=24,
    )
    pages = [
        page_summary(
            start_index=start_index,
            end_index=start_index + 99,
            item_count=100,
            expected_count=100,
            fetched_at=time.time(),
            is_partial=False,
        )
        for start_index in range(0, 5000, 100)
        if start_index not in {900, 4900}
    ]

    targets = select_rank_page_refresh_targets(
        [("测试", spec)],
        {"测试": pages},
        config=config,
    )

    actual = [(target.reason, target.start_rank, target.end_rank) for target in targets]
    assert actual == [
        (REFRESH_REASON_MISSING, 901, 1000),
        (REFRESH_REASON_MISSING, 4901, 5000),
    ]


def test_select_rank_page_refresh_targets_scores_partial_by_missing_ratio() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    config = RankPageRefreshConfig(
        target_limit=300,
        page_size=100,
        pages_per_run=1,
        refresh_stale_after_hours=24,
    )
    pages = [
        page_summary(
            start_index=0,
            end_index=99,
            item_count=10,
            expected_count=100,
            fetched_at=time.time(),
            is_partial=True,
        ),
        page_summary(
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


def test_select_rank_page_refresh_targets_scores_older_stale_pages_higher() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    config = RankPageRefreshConfig(
        target_limit=300,
        stale_age_weight=2.0,
        stale_age_max_multiplier=10.0,
        page_size=100,
        pages_per_run=1,
        refresh_stale_after_hours=24,
    )
    pages = [
        page_summary(
            start_index=0,
            end_index=99,
            item_count=100,
            expected_count=100,
            fetched_at=time.time(),
            is_partial=False,
        ),
        page_summary(
            start_index=100,
            end_index=199,
            item_count=100,
            expected_count=100,
            fetched_at=time.time() - 25 * 3600,
            is_partial=False,
        ),
        page_summary(
            start_index=200,
            end_index=299,
            item_count=100,
            expected_count=100,
            fetched_at=time.time() - 96 * 3600,
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
        (REFRESH_REASON_STALE, 201, 300)
    ]


def test_select_rank_page_refresh_targets_caps_stale_age_score() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    config = RankPageRefreshConfig(
        target_limit=200,
        stale_age_weight=100.0,
        stale_age_max_multiplier=2.0,
        page_size=100,
        pages_per_run=1,
        refresh_stale_after_hours=24,
    )
    pages = [
        page_summary(
            start_index=0,
            end_index=99,
            item_count=100,
            expected_count=100,
            fetched_at=time.time() - 25 * 3600,
            is_partial=False,
        ),
        page_summary(
            start_index=100,
            end_index=199,
            item_count=100,
            expected_count=100,
            fetched_at=time.time() - 240 * 3600,
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


def test_rank_page_refresh_uses_per_rank_target_limit() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    config = RankPageRefreshConfig(
        target_limit=500,
        target_limits={"测试": PER_RANK_TARGET_LIMIT},
        page_size=100,
        pages_per_run=5,
    )

    targets = select_rank_page_refresh_targets(
        [("测试", spec)],
        {"测试": []},
        config=config,
    )

    assert rank_target_limit(config, "测试") == PER_RANK_TARGET_LIMIT
    assert [(target.start_rank, target.end_rank) for target in targets] == [
        (1, 100),
        (101, 200),
    ]


def test_rank_page_refresh_score_cutoff_stops_after_boundary_page() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    config = RankPageRefreshConfig(
        target_limit=500,
        score_cutoffs={"测试": TEST_SCORE_CUTOFF},
        page_size=100,
        pages_per_run=5,
        refresh_stale_after_hours=24,
    )
    pages = [
        page_summary(
            start_index=0,
            end_index=99,
            item_count=100,
            expected_count=100,
            fetched_at=time.time(),
            min_score=1200,
            is_partial=False,
        ),
        page_summary(
            start_index=100,
            end_index=199,
            item_count=100,
            expected_count=100,
            fetched_at=time.time() - 48 * 3600,
            min_score=900,
            is_partial=False,
        ),
    ]

    targets = select_rank_page_refresh_targets(
        [("测试", spec)],
        {"测试": pages},
        config=config,
    )

    assert rank_score_cutoff(config, "测试") == TEST_SCORE_CUTOFF
    assert rank_refresh_target_label(config, "测试") == TEST_SCORE_TARGET_LABEL
    actual = [(target.reason, target.start_rank, target.end_rank) for target in targets]
    assert actual == [(REFRESH_REASON_STALE, 101, 200)]


def test_filter_standard_rank_page_summaries_ignores_lookup_fragments() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    config = RankPageRefreshConfig(target_limit=300, page_size=100)
    pages = [
        page_summary(start_index=0, end_index=0),
        page_summary(start_index=0, end_index=99),
        page_summary(start_index=23, end_index=23),
        page_summary(start_index=100, end_index=199),
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


def test_filter_standard_rank_page_summaries_uses_per_rank_target_limit() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    config = RankPageRefreshConfig(
        target_limit=300,
        target_limits={"测试": 200},
        page_size=100,
    )
    pages = [
        page_summary(start_index=0, end_index=99),
        page_summary(start_index=100, end_index=199),
        page_summary(start_index=200, end_index=299),
    ]

    filtered = filter_standard_rank_page_summaries(
        spec,
        pages,
        rank_key="测试",
        config=config,
    )

    assert [(page.start_index, page.end_index) for page in filtered] == [
        (0, 99),
        (100, 199),
    ]


def test_filter_standard_rank_page_summaries_stops_at_score_cutoff() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    config = RankPageRefreshConfig(
        target_limit=300,
        score_cutoffs={"测试": TEST_SCORE_CUTOFF},
        page_size=100,
    )
    pages = [
        page_summary(start_index=0, end_index=99, min_score=1200),
        page_summary(start_index=100, end_index=199, min_score=900),
        page_summary(start_index=200, end_index=299, min_score=100),
    ]

    filtered = filter_standard_rank_page_summaries(
        spec,
        pages,
        rank_key="测试",
        config=config,
    )

    assert [(page.start_index, page.end_index) for page in filtered] == [
        (0, 99),
        (100, 199),
    ]
