from types import SimpleNamespace

from ironsbot.services.seer.rank_list import (
    GlobalRankSpec,
    LocalRankSpec,
    RankCacheBatchCommand,
    RankListCommand,
    RankPageCacheRefreshCommand,
    RankPageCacheStatusCommand,
    batch_raw_start,
    build_local_rank_cache_status_message,
    build_local_rank_refresh_empty_message,
    build_local_rank_refresh_result_message,
    build_local_rank_refresh_start_message,
    build_rank_batch_no_players_message,
    build_rank_batch_result_message,
    build_rank_batch_start_message,
    build_rank_page_cache_overview_message,
    build_rank_page_cache_status_message,
    build_rank_page_refresh_result_message,
    build_rank_page_refresh_start_message,
    format_global_rank_line,
    format_global_rank_message,
    format_local_rank_message,
    format_rank_intervals,
    merge_rank_intervals,
    page_cache_rank_interval,
    parse_rank_cache_batch_command,
    parse_rank_list_command,
    parse_rank_page_cache_refresh_command,
    parse_rank_page_cache_status_command,
    timestamp_text,
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
    assert parse_rank_list_command("样本群星牌榜") is None


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
    assert format_global_rank_message(
        spec,
        [item],
        timestamp="2026-06-12 10:00:00",
        start_rank=21,
        requested_count=20,
    ) == "测试榜（第 21 名，截至2026-06-12 10:00:00）\n21. Alice（100） 123分"
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


def test_build_rank_page_cache_status_message_shows_partial_and_next_ranges() -> None:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    pages = [
        SimpleNamespace(
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
        target_limit=500,
        next_ranges=(("部分", 1, 100),),
    ) == (
        "📦【测试榜缓存】\n"
        "目标：前 500 名\n"
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
        SimpleNamespace(
            start_index=0,
            item_count=90,
            expected_count=100,
            is_stale=True,
            is_partial=True,
        ),
        SimpleNamespace(
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
    target = SimpleNamespace(
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
                [SimpleNamespace(item_count=100, is_partial=False, is_stale=False)],
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
        SimpleNamespace(total=0, success=0, failed=0, refreshed=[], failures=[])
    ) == "✅【榜单页缓存刷新】当前没有缺失、部分缺失或过期页面。"


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
    stats = SimpleNamespace(
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
    before_stats = SimpleNamespace(player_count=10, max_players=100)
    after_stats = SimpleNamespace(player_count=11, max_players=100)
    result = SimpleNamespace(total=10, success=9, skipped_full=0, failed=1)

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
