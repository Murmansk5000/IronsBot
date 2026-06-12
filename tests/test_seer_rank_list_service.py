from types import SimpleNamespace

from ironsbot.services.seer.rank_list import (
    GlobalRankSpec,
    LocalRankSpec,
    RankCacheBatchCommand,
    RankListCommand,
    RankPageCacheStatusCommand,
    batch_raw_start,
    build_rank_page_cache_status_message,
    format_global_rank_line,
    format_global_rank_message,
    format_local_rank_message,
    format_rank_intervals,
    merge_rank_intervals,
    page_cache_rank_interval,
    parse_rank_cache_batch_command,
    parse_rank_list_command,
    parse_rank_page_cache_status_command,
    with_admin_prefix,
)


def test_parse_rank_list_command_reads_global_aliases() -> None:
    assert parse_rank_list_command("图鉴榜") == RankListCommand(
        kind="global",
        rank_key="图鉴积分",
    )
    assert parse_rank_list_command("刻印图鉴榜") == RankListCommand(
        kind="global",
        rank_key="刻印图鉴",
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


def test_parse_rank_list_command_ignores_unknown_text() -> None:
    assert parse_rank_list_command("榜单帮助") is None
    assert parse_rank_list_command("米米号查询") is None


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
    assert parse_rank_page_cache_status_command("/榜单缓存 刻印榜") == (
        RankPageCacheStatusCommand(rank_key="刻印图鉴")
    )
    assert parse_rank_page_cache_status_command("/缓存区间图鉴榜") == (
        RankPageCacheStatusCommand(rank_key="图鉴积分")
    )
    assert parse_rank_page_cache_status_command("/榜单缓存 样本图鉴榜") is None


def test_with_admin_prefix_adds_slash_to_commands() -> None:
    assert with_admin_prefix(("缓存状态", "刷新样本榜")) == (
        "/缓存状态",
        "/刷新样本榜",
    )


def test_format_global_rank_line_applies_spec_rank_offset() -> None:
    spec = GlobalRankSpec(
        title="测试榜",
        key=1,
        sub_key=2,
        unit="分",
        start=10,
        rank_offset=-2,
    )
    item = SimpleNamespace(nick="Alice", id=100, score=123)

    assert format_global_rank_line(item, index=10, spec=spec) == (
        "9. Alice（100） 123分"
    )


def test_format_global_rank_message_uses_timestamp_and_empty_message() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    item = SimpleNamespace(nick="Alice", id=100, score=123)

    assert format_global_rank_message(
        spec,
        [item],
        timestamp="2026-06-12 10:00:00",
    ) == "测试榜（截至2026-06-12 10:00:00）\n1. Alice（100） 123分"
    assert format_global_rank_message(spec, []) == "❌找不到测试榜数据。"


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
    page = SimpleNamespace(start_index=10, item_count=5)

    assert page_cache_rank_interval(page, spec) == (9, 13)
    assert page_cache_rank_interval(
        SimpleNamespace(start_index=10, item_count=0),
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
        SimpleNamespace(start_index=0, item_count=2, is_stale=False),
        SimpleNamespace(start_index=2, item_count=2, is_stale=False),
        SimpleNamespace(start_index=10, item_count=3, is_stale=True),
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


def test_format_local_rank_message_uses_sample_and_season_context() -> None:
    spec = LocalRankSpec("样本测试榜", "test_metric", season_limited=True)
    entry = SimpleNamespace(
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
