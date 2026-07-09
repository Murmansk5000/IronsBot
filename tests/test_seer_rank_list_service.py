from dataclasses import dataclass, field

from ironsbot.services.seer.rank_cache_messages import (
    build_local_rank_cache_status_message,
    build_local_rank_refresh_empty_message,
    build_local_rank_refresh_result_message,
    build_local_rank_refresh_start_message,
    build_rank_batch_no_players_message,
    build_rank_batch_result_message,
    build_rank_batch_start_message,
)
from ironsbot.services.seer.rank_list_formatting import (
    batch_raw_start,
    format_rank_intervals,
    merge_rank_intervals,
    page_cache_rank_interval,
    timestamp_text,
)
from ironsbot.services.seer.rank_list_global_messages import (
    format_global_rank_line,
    format_global_rank_message,
)
from ironsbot.services.seer.rank_list_messages import format_local_rank_message
from ironsbot.services.seer.rank_list_models import (
    GlobalRankSpec,
    LocalRankSpec,
    RankCacheBatchCommand,
    RankListCommand,
    RankPageCacheRefreshCommand,
    RankPageCacheStatusCommand,
    RankScoreCommand,
)
from ironsbot.services.seer.rank_list_parsing import (
    parse_rank_cache_batch_command,
    parse_rank_list_command,
    parse_rank_page_cache_refresh_command,
    parse_rank_page_cache_status_command,
    parse_rank_score_command,
    with_admin_prefix,
)
from ironsbot.services.seer.rank_list_score_messages import (
    format_global_rank_score_message,
)
from ironsbot.services.seer.rank_page_cache_messages import (
    build_rank_page_cache_overview_message,
    build_rank_page_cache_status_message,
    build_rank_page_refresh_result_message,
    build_rank_page_refresh_start_message,
)


@dataclass(frozen=True)
class RankItem:
    id: int
    nick: str
    score: int
    rank_index: int = 0


@dataclass(frozen=True)
class ScoreGap:
    score: int
    start_rank: int
    end_rank: int
    total_count: int
    truncated: bool = False
    items: list[RankItem] = field(default_factory=list)


@dataclass(frozen=True)
class ScoreResult:
    queried: bool
    target_score: int
    searched_limit: int
    boundary_score: int | None
    items: list[RankItem]
    start_rank: int | None = None
    end_rank: int | None = None
    total_count: int = 0
    truncated: bool = False
    higher_gap: ScoreGap | None = None
    lower_gap: ScoreGap | None = None


@dataclass(frozen=True)
class PageSummary:
    start_index: int
    item_count: int
    end_index: int = 0
    expected_count: int = 0
    is_stale: bool = False
    is_partial: bool = False

    def __post_init__(self) -> None:
        if self.expected_count == 0:
            object.__setattr__(self, "expected_count", self.item_count)


@dataclass(frozen=True)
class RefreshTarget:
    reason: str
    start_rank: int
    end_rank: int
    spec: GlobalRankSpec


@dataclass(frozen=True)
class PageRefreshResult:
    total: int
    success: int
    failed: int
    refreshed: list[RefreshTarget] = field(default_factory=list)
    failures: list[object] = field(default_factory=list)


@dataclass(frozen=True)
class LocalRankEntry:
    rank: int
    nick: str
    user_id: int
    display: str


@dataclass(frozen=True)
class LocalRankStats:
    player_count: int
    max_players: int
    total_player_count: int = 0
    metric_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalRefreshResult:
    total: int
    success: int
    skipped_full: int
    failed: int


def test_parse_rank_list_command_reads_global_aliases() -> None:
    assert parse_rank_list_command("图鉴榜") == RankListCommand(
        kind="global",
        rank_key="图鉴积分",
    )
    assert parse_rank_list_command("刻印图鉴榜") == RankListCommand(
        kind="global",
        rank_key="刻印图鉴",
    )
    assert parse_rank_list_command("皮肤榜第2页") == RankListCommand(
        kind="global",
        rank_key="皮肤图鉴",
        start_rank=11,
        limit=10,
    )
    assert parse_rank_list_command("成就榜第100名") == RankListCommand(
        kind="global",
        rank_key="成就点数",
        start_rank=100,
        limit=1,
    )
    assert parse_rank_list_command("群星牌榜") == RankListCommand(
        kind="global",
        rank_key="群星牌",
    )
    assert parse_rank_list_command("群星之巅榜第2页") == RankListCommand(
        kind="global",
        rank_key="群星牌",
        start_rank=11,
        limit=10,
    )
    assert parse_rank_list_command("竞技段位榜50名") == RankListCommand(
        kind="global",
        rank_key="竞技段位",
        start_rank=50,
        limit=1,
    )
    assert parse_rank_list_command("竞技榜") == RankListCommand(
        kind="global",
        rank_key="竞技段位",
    )
    assert parse_rank_list_command("狂野榜20名") == RankListCommand(
        kind="global",
        rank_key="狂野段位",
        start_rank=20,
        limit=1,
    )
    assert parse_rank_list_command("专家段位榜") == RankListCommand(
        kind="global",
        rank_key="专家段位",
    )
    assert parse_rank_list_command("专家榜") == RankListCommand(
        kind="global",
        rank_key="专家段位",
    )


def test_parse_rank_score_command_reads_global_score_query() -> None:
    assert parse_rank_score_command("群星牌榜3149分") == RankScoreCommand(
        rank_key="群星牌",
        score=3149,
    )
    assert parse_rank_score_command("成就榜13605点") == RankScoreCommand(
        rank_key="成就点数",
        score=13605,
    )
    assert parse_rank_score_command("成就榜13605分") == RankScoreCommand(
        rank_key="成就点数",
        score=13605,
    )
    assert parse_rank_score_command("竞技段位榜400036分") == RankScoreCommand(
        rank_key="竞技段位",
        score=400036,
    )
    assert parse_rank_score_command("竞技段位榜王者0分") == RankScoreCommand(
        rank_key="竞技段位",
        score=300000,
    )
    assert parse_rank_score_command("竞技段位榜王者0星") == RankScoreCommand(
        rank_key="竞技段位",
        score=300000,
    )
    assert parse_rank_score_command("狂野段位榜圣皇36星") == RankScoreCommand(
        rank_key="狂野段位",
        score=400036,
    )
    assert parse_rank_score_command("狂野榜圣皇36星") == RankScoreCommand(
        rank_key="狂野段位",
        score=400036,
    )
    assert parse_rank_score_command("狂野段位榜宇宙圣皇100星") == RankScoreCommand(
        rank_key="狂野段位",
        score=400100,
    )
    assert parse_rank_score_command("狂野段位榜宇宙圣皇136") == RankScoreCommand(
        rank_key="狂野段位",
        score=400136,
    )
    assert parse_rank_score_command("狂野段位榜宇宙圣皇1") is None
    assert parse_rank_score_command("专家段位榜3000分") == RankScoreCommand(
        rank_key="专家段位",
        score=3000,
    )
    assert parse_rank_score_command("专家段位榜王者0分") is None
    assert parse_rank_score_command("样本群星牌榜3149分") is None
    assert parse_rank_score_command("群星牌榜第3149名") is None


def test_parse_rank_list_command_uses_configured_default_limit() -> None:
    assert parse_rank_list_command("皮肤榜", default_limit=30) == RankListCommand(
        kind="global",
        rank_key="皮肤图鉴",
        limit=30,
    )
    assert parse_rank_list_command(
        "皮肤榜第2页",
        default_limit=30,
    ) == RankListCommand(
        kind="global",
        rank_key="皮肤图鉴",
        start_rank=31,
        limit=30,
    )
    assert parse_rank_list_command("皮肤榜1-200") == RankListCommand(
        kind="global",
        rank_key="皮肤图鉴",
        start_rank=1,
        limit=100,
    )


def test_parse_rank_list_command_reads_local_aliases() -> None:
    assert parse_rank_list_command("样本图鉴榜") == RankListCommand(
        kind="local",
        rank_key="图鉴积分",
    )
    assert parse_rank_list_command("机器人精灵总数榜") == RankListCommand(
        kind="local",
        rank_key="精灵数量",
    )
    assert parse_rank_list_command("样本皮肤榜21-40") == RankListCommand(
        kind="local",
        rank_key="皮肤图鉴",
        start_rank=21,
        limit=20,
    )
    assert parse_rank_list_command("样本群星牌榜") == RankListCommand(
        kind="local",
        rank_key="群星牌",
    )
    assert parse_rank_list_command("样本群星牌积分榜") == RankListCommand(
        kind="local",
        rank_key="群星牌",
    )


def test_parse_rank_list_command_ignores_unknown_text() -> None:
    assert parse_rank_list_command("榜单帮助") is None
    assert parse_rank_list_command("米米号查询") is None
    assert parse_rank_list_command("图鉴榜第0页") is None
    assert parse_rank_list_command("图鉴榜100-1") is None


def test_parse_rank_cache_batch_command_requires_admin_prefix_and_global_rank() -> None:
    assert parse_rank_cache_batch_command("/缓存榜单 图鉴榜 1-100") == (
        RankCacheBatchCommand(
            rank_key="图鉴积分",
            start_rank=1,
            end_rank=100,
        )
    )
    assert parse_rank_cache_batch_command("/缓存排行刻印榜20到40") == (
        RankCacheBatchCommand(
            rank_key="刻印图鉴",
            start_rank=20,
            end_rank=40,
        )
    )
    assert parse_rank_cache_batch_command("缓存榜单 图鉴榜 1-100") is None
    assert parse_rank_cache_batch_command("/缓存榜单 样本图鉴榜 1-100") is None
    assert parse_rank_cache_batch_command("/缓存榜单 图鉴榜 100-1") is None


def test_parse_rank_page_cache_status_command_reads_global_rank() -> None:
    assert parse_rank_page_cache_status_command("/榜单情况 刻印榜") == (
        RankPageCacheStatusCommand(rank_key="刻印图鉴")
    )
    assert parse_rank_page_cache_status_command("/榜单状态图鉴榜") == (
        RankPageCacheStatusCommand(rank_key="图鉴积分")
    )
    assert parse_rank_page_cache_status_command("/榜单情况 群星牌榜") == (
        RankPageCacheStatusCommand(rank_key="群星牌")
    )
    assert parse_rank_page_cache_status_command("/榜单情况 样本图鉴榜") is None
    assert parse_rank_page_cache_status_command("/榜单缓存 刻印榜") is None


def test_parse_rank_page_cache_refresh_command_reads_optional_global_rank() -> None:
    assert parse_rank_page_cache_refresh_command("/刷新榜单") == (
        RankPageCacheRefreshCommand()
    )
    assert parse_rank_page_cache_refresh_command("/刷新榜单 皮肤榜") == (
        RankPageCacheRefreshCommand(rank_key="皮肤图鉴")
    )
    assert parse_rank_page_cache_refresh_command("/刷新榜单 样本图鉴榜") is None
    assert parse_rank_page_cache_refresh_command("/刷新榜单缓存 皮肤榜") is None
    assert parse_rank_page_cache_refresh_command("刷新榜单 皮肤榜") is None


def test_with_admin_prefix_adds_slash_to_commands() -> None:
    assert with_admin_prefix(("样本情况", "刷新样本")) == (
        "/样本情况",
        "/刷新样本",
    )


def test_timestamp_text_uses_china_timezone() -> None:
    assert timestamp_text(0) == "1970-01-01 08:00:00"


def test_format_global_rank_line_applies_spec_rank_offset() -> None:
    spec = GlobalRankSpec(
        title="测试榜",
        key=1,
        sub_key=2,
        unit="分",
        start=10,
        rank_offset=-2,
    )
    item = RankItem(nick="Alice", id=100, score=123)

    assert format_global_rank_line(item, index=10, spec=spec) == (
        "9. Alice（100） 123分"
    )


def test_format_global_rank_line_formats_peak_rating_score() -> None:
    spec = GlobalRankSpec(
        "竞技段位榜",
        key=120,
        sub_key=20260417,
        unit="分",
        score_format="peak_rating",
    )
    item = RankItem(nick="Alice", id=100, score=400136)

    assert format_global_rank_line(item, index=0, spec=spec) == (
        "1. Alice（100） 宇宙圣皇136星（400136）"
    )


def test_format_global_rank_message_uses_timestamp_and_empty_message() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    item = RankItem(nick="Alice", id=100, score=123)

    assert format_global_rank_message(
        spec,
        [item],
        timestamp="2026-06-12 10:00:00",
    ) == "测试榜（截至2026-06-12 10:00:00）\n1. Alice（100） 123分"
    assert format_global_rank_message(
        spec,
        [item],
        timestamp="2026-06-12 10:00:00",
        start_rank=21,
        requested_count=20,
    ) == "测试榜（第 21 名，截至2026-06-12 10:00:00）\n21. Alice（100） 123分"
    assert format_global_rank_message(spec, []) == "❌找不到测试榜数据。"


def test_format_global_rank_score_message() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    result = ScoreResult(
        queried=True,
        target_score=3149,
        searched_limit=10000,
        boundary_score=1000,
        start_rank=21,
        end_rank=23,
        total_count=3,
        truncated=False,
        items=[
            RankItem(id=101, nick="Alice", score=3149, rank_index=20),
            RankItem(id=102, nick="Bob", score=3149, rank_index=21),
            RankItem(id=103, nick="Carol", score=3149, rank_index=22),
        ],
    )

    assert format_global_rank_score_message(
        spec,
        result,
        display_limit=2,
        timestamp="2026-06-12 10:00:00",
    ) == (
        "测试榜（3149分，第 21-23 名，共 3 人，截至2026-06-12 10:00:00）\n"
        "21. Alice（101） 3149分\n"
        "22. Bob（102） 3149分\n"
        "...另 1 人未展示"
    )


def test_format_global_rank_score_message_shows_cached_hit_without_boundary() -> None:
    spec = GlobalRankSpec("图鉴积分榜", key=156, sub_key=1, unit="分")
    result = ScoreResult(
        queried=True,
        target_score=55933,
        searched_limit=10000,
        boundary_score=None,
        start_rank=200,
        end_rank=200,
        total_count=1,
        truncated=False,
        items=[
            RankItem(
                id=291439942,
                nick="桐生 战兔",
                score=55933,
                rank_index=199,
            ),
        ],
    )

    assert format_global_rank_score_message(
        spec,
        result,
        timestamp="2026-07-07 16:33:27",
    ) == (
        "图鉴积分榜（55933分，第 200-200 名，共 1 人，截至2026-07-07 16:33:27）\n"
        "200. 桐生 战兔（291439942） 55933分"
    )


def test_format_rank_score_message_needs_data_without_items_or_boundary() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    result = ScoreResult(
        queried=True,
        target_score=3149,
        searched_limit=10000,
        boundary_score=None,
        items=[],
    )

    assert format_global_rank_score_message(spec, result) == "❌找不到测试榜数据。"


def test_format_global_rank_score_message_keeps_boundary_rejection() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    result = ScoreResult(
        queried=True,
        target_score=999,
        searched_limit=10000,
        boundary_score=1000,
        items=[],
    )

    assert format_global_rank_score_message(spec, result) == (
        "❌999分不在测试榜前 10000 名范围内。\n"
        "当前范围末位约为 1000分。"
    )


def test_format_global_rank_score_message_shows_missing_score_proof() -> None:
    spec = GlobalRankSpec("群星之巅榜", key=240, sub_key=1, unit="分")
    result = ScoreResult(
        queried=True,
        target_score=10000,
        searched_limit=50000,
        boundary_score=9970,
        items=[],
        higher_gap=ScoreGap(
            score=10001,
            start_rank=57,
            end_rank=57,
            total_count=1,
            truncated=False,
            items=[
                RankItem(
                    id=910731260,
                    nick="流苏",
                    score=10001,
                    rank_index=56,
                )
            ],
        ),
        lower_gap=ScoreGap(
            score=9970,
            start_rank=58,
            end_rank=58,
            total_count=1,
            truncated=False,
            items=[
                RankItem(
                    id=264391071,
                    nick="慎重格劳瑞",
                    score=9970,
                    rank_index=57,
                )
            ],
        ),
    )

    assert format_global_rank_score_message(spec, result) == (
        "❌群星之巅榜没有10000分的用户。\n"
        "相邻分数段：\n"
        "10001分：第 57 名，共 1 人\n"
        "57. 流苏（910731260） 10001分\n"
        "9970分：第 58 名，共 1 人\n"
        "58. 慎重格劳瑞（264391071） 9970分"
    )


def test_batch_raw_start_respects_spec_start_and_rank_offset() -> None:
    first_rank_raw_start = 8
    rank_30_raw_start = 37
    spec = GlobalRankSpec(
        title="测试榜",
        key=1,
        sub_key=2,
        unit="项",
        start=8,
        rank_offset=-8,
    )

    assert batch_raw_start(spec, 1) == first_rank_raw_start
    assert batch_raw_start(spec, 30) == rank_30_raw_start


def test_page_cache_rank_interval_and_interval_formatting() -> None:
    spec = GlobalRankSpec(
        title="测试榜",
        key=1,
        sub_key=2,
        unit="项",
        rank_offset=-2,
    )
    page = PageSummary(start_index=10, item_count=5)

    assert page_cache_rank_interval(page, spec) == (9, 13)
    assert page_cache_rank_interval(
        PageSummary(start_index=10, item_count=0),
        spec,
    ) is None
    assert merge_rank_intervals([(5, 6), (1, 3), (4, 4), (10, 10)]) == [
        (1, 6),
        (10, 10),
    ]
    assert format_rank_intervals([(1, 6), (10, 10)]) == "1-6、10"
    assert format_rank_intervals([]) == "无"


def test_build_rank_page_cache_status_message_groups_valid_and_stale_pages() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    pages = [
        PageSummary(start_index=0, item_count=2, is_stale=False),
        PageSummary(start_index=2, item_count=2, is_stale=False),
        PageSummary(start_index=10, item_count=3, is_stale=True),
    ]

    assert build_rank_page_cache_status_message(
        spec,
        pages,
        ttl_seconds=3600,
    ) == (
        "📦【测试榜缓存】\n"
        "有效缓存：2 段，4 名\n"
        "有效区间：1-4\n"
        "过期缓存：1 段，3 名\n"
        "过期区间：11-13\n"
        "TTL：3600 秒"
    )
    assert build_rank_page_cache_status_message(
        spec,
        [],
        ttl_seconds=3600,
    ) == "📦【测试榜缓存】\n当前没有缓存区间。"


def test_build_rank_page_cache_status_message_shows_partial_and_next_ranges() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    pages = [
        PageSummary(
            start_index=0,
            item_count=99,
            expected_count=100,
            is_stale=False,
            is_partial=True,
        )
    ]

    assert build_rank_page_cache_status_message(
        spec,
        pages,
        ttl_seconds=3600,
        target_limit="分数 >= 1000（最多前 500 名）",
        next_ranges=(("部分", 1, 100),),
    ) == (
        "📦【测试榜缓存】\n"
        "目标：分数 >= 1000（最多前 500 名）\n"
        "有效缓存：0 段，0 名\n"
        "有效区间：无\n"
        "部分缺失：1 段，现存 99 名\n"
        "缺失区间：1-100\n"
        "TTL：3600 秒\n"
        "下一刷：部分:1-100"
    )


def test_build_rank_page_cache_status_does_not_double_count_partial_stale() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    pages = [
        PageSummary(
            start_index=0,
            item_count=90,
            expected_count=100,
            is_stale=True,
            is_partial=True,
        ),
        PageSummary(
            start_index=100,
            item_count=100,
            expected_count=100,
            is_stale=True,
            is_partial=False,
        ),
    ]

    assert build_rank_page_cache_status_message(
        spec,
        pages,
        ttl_seconds=3600,
        target_limit=500,
    ) == (
        "📦【测试榜缓存】\n"
        "目标：前 500 名\n"
        "有效缓存：0 段，0 名\n"
        "有效区间：无\n"
        "部分缺失：1 段，现存 90 名\n"
        "缺失区间：1-100\n"
        "过期缓存：1 段，100 名\n"
        "过期区间：101-200\n"
        "TTL：3600 秒"
    )


def test_build_rank_page_cache_overview_and_refresh_messages() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    target = RefreshTarget(
        reason="缺失",
        start_rank=101,
        end_rank=200,
        spec=spec,
    )
    assert build_rank_page_cache_overview_message(
        [
            (
                "测试",
                spec,
                [
                    PageSummary(
                        start_index=0,
                        item_count=100,
                        is_partial=False,
                        is_stale=False,
                    )
                ],
                [target],
                500,
            )
        ],
    ) == (
        "📦【榜单页缓存】\n"
        "测试榜：100/500 名，部分 0 页，过期 0 页，下一刷 缺失:101-200"
    )
    assert build_rank_page_refresh_start_message(
        RankPageCacheRefreshCommand(rank_key="皮肤图鉴")
    ) == "🔄 正在刷新皮肤图鉴榜缓存。"
    assert build_rank_page_refresh_result_message(
        PageRefreshResult(total=0, success=0, failed=0)
    ) == "✅【榜单页缓存刷新】当前没有缺失、部分缺失或过期页面。"


def test_format_local_rank_message_uses_sample_and_season_context() -> None:
    spec = LocalRankSpec("样本测试榜", "test_metric", season_limited=True)
    entry = LocalRankEntry(
        rank=1,
        nick="Alice",
        user_id=100,
        display="999分",
    )

    assert format_local_rank_message(
        spec,
        [entry],
        sample_count=9,
        timestamp="2026-06-12 10:00:00",
        season_sub_key="S42",
    ) == (
        "样本测试榜（样本9人，截至2026-06-12 10:00:00）\n"
        "赛季样本：S42\n"
        "1. Alice（100） 999分"
    )
    assert format_local_rank_message(spec, [], sample_count=0) == (
        "❌暂无样本测试榜数据。先查询一些米米号后再试。"
    )


def test_build_rank_batch_admin_messages() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    command = RankCacheBatchCommand("图鉴积分", start_rank=1, end_rank=50)

    assert build_rank_batch_no_players_message(spec) == (
        "❌ 没有从测试榜拿到可缓存的榜单数据。"
    )
    assert build_rank_batch_start_message(
        spec,
        command,
        item_count=20,
        requested_count=50,
    ) == (
        "🔄 正在缓存测试榜第 1-50 名。\n"
        "实际拿到 20 条榜单数据。\n"
        "只写入全服榜单页缓存，不计入样本。\n"
        "本次按 seer.local_rank.batch_limit 只处理前 20 个。"
    )
    assert build_rank_batch_result_message(
        spec,
        command,
        item_count=20,
        requested_count=50,
    ) == (
        "✅【榜单区间缓存完成】\n"
        "榜单：测试榜\n"
        "请求区间：第 1-50 名\n"
        "写入榜单页缓存：20 条\n"
        "样本缓存：未写入\n"
        "本次实际缓存：20/50 条"
    )


def test_build_local_rank_cache_status_message() -> None:
    stats = LocalRankStats(
        player_count=10,
        total_player_count=15,
        max_players=100,
        metric_counts={"图鉴积分": 8, "竞技段位": 3},
    )

    assert build_local_rank_cache_status_message(
        stats,
        rank_limit=10000,
        batch_limit=100,
        refresh_limit=500,
        refresh_max_age_hours=24,
    ) == (
        "📊【样本榜缓存状态】\n"
        "已缓存米米号：10/100 个\n"
        "总缓存玩家：15 个（含全服榜单扫到但未计入样本的人）\n"
        "全服排行扫描上限：前 10000 名\n"
        "单次批量缓存上限：100 个\n"
        "单轮刷新上限：500 个\n"
        "刷新过期时间：24 小时\n"
        "巅峰样本：按当前赛季单独比较\n"
        "榜单命令展示：前 10 名\n"
        "\n"
        "可参与排行人数：\n"
        "图鉴积分：8\n"
        "竞技段位：3"
    )


def test_build_local_rank_refresh_messages() -> None:
    before_stats = LocalRankStats(player_count=10, max_players=100)
    after_stats = LocalRankStats(player_count=11, max_players=100)
    result = LocalRefreshResult(total=10, success=9, skipped_full=0, failed=1)

    assert build_local_rank_refresh_empty_message() == (
        "❌ 当前没有本地样本缓存。先查询一些米米号后再刷新。"
    )
    assert build_local_rank_refresh_start_message(
        before_stats,
        refresh_limit=1000,
        refresh_max_age_hours=24,
    ) == (
        "🔄 正在刷新样本榜缓存。样本共 10 个，"
        "本轮按最旧优先最多刷新 1000 个，只刷新超过 24 小时未更新的数据。"
    )
    assert build_local_rank_refresh_result_message(
        result,
        after_stats,
        failure_lines=("- 123: 查询超时",),
    ) == (
        "✅【样本榜缓存刷新完成】\n"
        "本轮候选米米号：10 个\n"
        "成功刷新：9 个\n"
        "缓存已满跳过：0 个\n"
        "失败：1 个\n"
        "当前缓存米米号：11/100 个\n"
        "\n"
        "失败示例：\n"
        "- 123: 查询超时"
    )
