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
TWO_ANGLE_COUNT = 2
FIVE_ANGLE_COUNT = 5
SIX_ANGLE_COUNT = 6
SHIELD_VALUE = 37.0
SHIELD_HP_VALUE = 57.0


def test_parse_countermark_stat_rank_command_reads_all_scope() -> None:
    command = parse_countermark_stat_rank_command("刻印攻击榜")

    assert command is not None
    assert command.scope == "all"
    assert command.stat == StatSpec("atk", "物攻", ("atk",))


def test_parse_countermark_stat_rank_command_rejects_ambiguous_attack() -> None:
    command = parse_countermark_stat_rank_command("刻印攻榜")

    assert command is not None
    assert command.stat is None


def test_parse_countermark_stat_rank_command_reads_five_angle_scope() -> None:
    command = parse_countermark_stat_rank_command("五角刻印速度榜")

    assert command is not None
    assert command.scope == "angle"
    assert command.angle_count == FIVE_ANGLE_COUNT
    assert command.stat == StatSpec("spd", "速度", ("spd",))


def test_parse_countermark_stat_rank_command_reads_two_angle_aliases() -> None:
    for text in ("二角刻印攻击榜", "两角刻印攻击榜", "2角刻印攻击榜"):
        command = parse_countermark_stat_rank_command(text)

        assert command is not None
        assert command.scope == "angle"
        assert command.angle_count == TWO_ANGLE_COUNT
        assert command.stat == StatSpec("atk", "物攻", ("atk",))


def test_parse_countermark_stat_rank_command_reads_six_angle_aliases() -> None:
    for text in ("六角刻印攻击榜", "6角刻印速度榜", "６角刻印总和榜"):
        command = parse_countermark_stat_rank_command(text)

        assert command is not None
        assert command.scope == "angle"
        assert command.angle_count == SIX_ANGLE_COUNT


def test_parse_countermark_stat_rank_command_reads_composite_stats() -> None:
    shield_command = parse_countermark_stat_rank_command("刻印盾榜")
    dual_attack_command = parse_countermark_stat_rank_command("六角双攻榜")

    assert shield_command is not None
    assert shield_command.stat == StatSpec(
        "shield",
        "盾",
        ("def_", "sp_def"),
    )
    assert shield_command.scope == "all"
    assert dual_attack_command is not None
    assert dual_attack_command.stat == StatSpec(
        "dual_atk",
        "双攻",
        ("atk", "sp_atk"),
    )
    assert dual_attack_command.scope == "angle"
    assert dual_attack_command.angle_count == SIX_ANGLE_COUNT


def test_parse_countermark_stat_rank_command_reads_stat_combinations() -> None:
    shield_hp_command = parse_countermark_stat_rank_command("刻印盾体榜")
    attack_hp_command = parse_countermark_stat_rank_command("物攻体刻印榜")
    special_attack_shield_command = parse_countermark_stat_rank_command(
        "特攻盾刻印榜"
    )

    assert shield_hp_command is not None
    assert shield_hp_command.stat == StatSpec(
        "combo:def_+sp_def+hp",
        "盾体力",
        ("def_", "sp_def", "hp"),
    )
    assert attack_hp_command is not None
    assert attack_hp_command.stat == StatSpec(
        "combo:atk+hp",
        "物攻体力",
        ("atk", "hp"),
    )
    assert special_attack_shield_command is not None
    assert special_attack_shield_command.stat == StatSpec(
        "combo:sp_atk+def_+sp_def",
        "特攻盾",
        ("sp_atk", "def_", "sp_def"),
    )


def test_parse_countermark_stat_rank_command_requires_countermark_marker() -> None:
    assert parse_countermark_stat_rank_command("盾体榜") is None


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
    assert (
        "可用属性：攻击 / 防御 / 特攻 / 特防 / 速度 / 体力 / 盾 / 双攻 / 总和"
        in message
    )


def test_build_countermark_message_explains_empty_five_angle_result() -> None:
    message = build_countermark_stat_rank_message(
        CountermarkStatRankCommand(
            stat=StatSpec("spd", "速度"),
            scope="angle",
            angle_count=5,
        ),
        [],
    )

    assert "没有找到5角刻印的速度数据" in message
    assert "六角刻印速度榜 或 2角刻印速度榜" in message


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
        CountermarkStatRankCommand(stat=StatSpec("atk", "物攻"), scope="all"),
        [item],
        now_text="2026-06-12 09:30:00",
    )

    assert "💮【所有刻印物攻榜】（截至2026-06-12 09:30:00）" in message
    assert "范围：所有刻印 | 展示前 1 名" in message
    assert "1. 怒火刻印（1001） 物攻42 | 总和66.5 | 限定 | 5角" in message


def test_build_countermark_message_renders_composite_stats() -> None:
    item = CountermarkStatRankItem(
        mintmark=cast(
            "Any",
            SimpleNamespace(
                id=1002,
                name="守护刻印",
            ),
        ),
        attrs=cast("Any", SimpleNamespace(total=TOTAL_VALUE)),
        value=SHIELD_VALUE,
        total=TOTAL_VALUE,
        class_name="限定",
        angle_count=SIX_ANGLE_COUNT,
    )

    message = build_countermark_stat_rank_message(
        CountermarkStatRankCommand(
            stat=StatSpec("shield", "盾"),
            scope="angle",
            angle_count=SIX_ANGLE_COUNT,
        ),
        [item],
        now_text="2026-06-12 09:30:00",
    )

    assert "💮【6角刻印盾榜】（截至2026-06-12 09:30:00）" in message
    assert "1. 守护刻印（1002） 盾37 | 总和66.5 | 限定 | 6角" in message


def test_build_countermark_message_renders_stat_combinations() -> None:
    item = CountermarkStatRankItem(
        mintmark=cast(
            "Any",
            SimpleNamespace(
                id=1003,
                name="厚重刻印",
            ),
        ),
        attrs=cast("Any", SimpleNamespace(total=TOTAL_VALUE)),
        value=SHIELD_HP_VALUE,
        total=TOTAL_VALUE,
        class_name="限定",
        angle_count=TWO_ANGLE_COUNT,
    )

    message = build_countermark_stat_rank_message(
        CountermarkStatRankCommand(
            stat=StatSpec(
                "combo:def_+sp_def+hp",
                "盾体力",
                ("def_", "sp_def", "hp"),
            ),
            scope="angle",
            angle_count=TWO_ANGLE_COUNT,
        ),
        [item],
        now_text="2026-06-12 09:30:00",
    )

    assert "💮【2角刻印盾体力榜】（截至2026-06-12 09:30:00）" in message
    assert "1. 厚重刻印（1003） 盾体力57 | 总和66.5 | 限定 | 2角" in message
