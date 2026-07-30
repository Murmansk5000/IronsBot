from ironsbot.app.command_directory.seer import rank_commands
from ironsbot.services.seer.rank_help import format_rank_help
from ironsbot.services.seer.rank_list_models import (
    GLOBAL_RANKS,
    LOCAL_RANKS,
    GlobalRankSpec,
    LocalRankSpec,
)


def test_rank_help_documents_parseable_query_forms() -> None:
    message = format_rank_help(
        "【管理】\n/刷新榜单 - 刷新缓存",
        global_ranks={"global": GlobalRankSpec("全服测试榜", 1, 2, "分")},
        local_ranks={"local": LocalRankSpec("样本测试榜", "score")},
    )

    assert "成就榜第2页" in message
    assert "成就榜21-40" in message
    assert "成就榜123456789" in message
    assert "成就榜5000点" in message
    assert "群星牌榜3149分" in message
    assert "竞技段位榜王者0星" in message
    assert "样本皮肤榜21-40" in message
    assert "默认查询全部角数" in message
    assert "全服测试榜" in message
    assert "样本测试榜" in message
    assert "/刷新榜单" in message


def test_rank_command_examples_are_derived_from_rank_specs() -> None:
    commands = {command.id: command for command in rank_commands()}

    assert commands["rank.global_collection"].examples == tuple(
        spec.title
        for spec in GLOBAL_RANKS.values()
        if not spec.peak_season_sub_key
    )
    assert commands["rank.sample_peak"].examples == tuple(
        spec.title
        for spec in LOCAL_RANKS.values()
        if spec.season_limited
    )
