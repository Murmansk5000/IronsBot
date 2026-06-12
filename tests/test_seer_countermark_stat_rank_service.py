from types import SimpleNamespace
from typing import Any, cast

from ironsbot.services.seer.countermark_stat_rank import (
    CountermarkStatRankCommand,
    CountermarkStatRankItem,
    StatSpec,
    build_countermark_stat_rank_message,
    parse_countermark_stat_rank_command,
)

ATTACK_VALUE = 42.0
TOTAL_VALUE = 66.5


def test_parse_countermark_stat_rank_command_reads_all_scope() -> None:
    command = parse_countermark_stat_rank_command("刻印攻击榜")

    assert command is not None
    assert command.scope == "all"
    assert command.stat == StatSpec("atk", "攻击")


def test_parse_countermark_stat_rank_command_reads_five_angle_scope() -> None:
    command = parse_countermark_stat_rank_command("五角刻印速度榜")

    assert command is not None
    assert command.scope == "five"
    assert command.stat == StatSpec("spd", "速度")


def test_parse_countermark_stat_rank_command_ignores_plain_countermark_rank() -> None:
    assert parse_countermark_stat_rank_command("刻印榜") is None
    assert parse_countermark_stat_rank_command("样本刻印图鉴榜") is None
    assert parse_countermark_stat_rank_command("米米号查询") is None


def test_build_countermark_message_prompts_when_stat_is_missing() -> None:
    message = build_countermark_stat_rank_message(
        CountermarkStatRankCommand(stat=None, scope="all"),
        [],
    )

    assert "刻印数值榜需要指定属性" in message
    assert "可用属性：攻击 / 防御 / 特攻 / 特防 / 速度 / 体力 / 总和" in message


def test_build_countermark_message_explains_empty_five_angle_result() -> None:
    message = build_countermark_stat_rank_message(
        CountermarkStatRankCommand(stat=StatSpec("spd", "速度"), scope="five"),
        [],
    )

    assert "没有找到五角刻印的速度数据" in message
    assert "五角刻印速度榜 或 5角刻印速度榜" in message


def test_build_countermark_message_renders_ranked_items() -> None:
    item = CountermarkStatRankItem(
        mintmark=cast(
            "Any",
            SimpleNamespace(
                id=1001,
                name="怒火刻印",
            ),
        ),
        attrs=cast("Any", SimpleNamespace(total=TOTAL_VALUE)),
        value=ATTACK_VALUE,
        total=TOTAL_VALUE,
        class_name="限定",
        angle_count=5,
    )

    message = build_countermark_stat_rank_message(
        CountermarkStatRankCommand(stat=StatSpec("atk", "攻击"), scope="all"),
        [item],
        now_text="2026-06-12 09:30:00",
    )

    assert "💮【所有刻印攻击榜】（截至2026-06-12 09:30:00）" in message
    assert "范围：所有刻印 | 展示前 1 名" in message
    assert "1. 怒火刻印（1001） 攻击42 | 总和66.5 | 限定 | 5角" in message
