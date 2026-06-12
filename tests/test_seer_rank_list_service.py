from ironsbot.services.seer.rank_list import (
    RankCacheBatchCommand,
    RankListCommand,
    RankPageCacheStatusCommand,
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
