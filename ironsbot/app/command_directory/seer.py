# SPDX-License-Identifier: MIT
from __future__ import annotations

from ironsbot.app.command_directory.rows import commands_from_rows
from ironsbot.runtime.commands import CommandAccess, CommandDescriptor
from ironsbot.services.seer.rank_catalog import rank_command_names
from ironsbot.services.seer.rank_list_models import GLOBAL_RANKS, LOCAL_RANKS


def _global_rank_titles(*, peak: bool) -> tuple[str, ...]:
    return tuple(
        rank_command_names("global", key)[0]
        for key, spec in GLOBAL_RANKS.items()
        if spec.peak_season_sub_key is peak
    )


def _local_rank_titles(*, peak: bool) -> tuple[str, ...]:
    return tuple(
        rank_command_names("local", key)[0]
        for key, spec in LOCAL_RANKS.items()
        if spec.season_limited is peak
    )


def seer_query_commands() -> tuple[CommandDescriptor, ...]:
    return (
        *commands_from_rows(
            "seer_query",
            "玩家",
            "seer_player",
            (
                (
                    "seer.player.query",
                    ("米米号123456", "查询玩家信息123456"),
                    "查询玩家基础信息；随后按提示回复数字查看详情",
                    {"show_in_poke": True},
                ),
                (
                    "seer.player.default",
                    ("米米号", "收集", "巅峰", "群星牌"),
                    ("查询已绑定默认米米号的对应数据；未绑定时使用“米米号+完整米米号”"),
                    {},
                ),
                (
                    "seer.player.bind",
                    ("绑定米米号123456",),
                    "查询并绑定默认米米号，之后可使用快捷查询",
                    {},
                ),
                (
                    "seer.player.unbind",
                    ("解绑米米号",),
                    "解除当前 QQ 绑定的默认米米号",
                    {},
                ),
            ),
        ),
        *commands_from_rows(
            "seer_query",
            "战队",
            "seer_team",
            (
                (
                    "seer.team.query",
                    ("战队123456", "战队123456 654321"),
                    "查询指定战队信息；一次最多查询 3 个战队",
                    {"show_in_poke": True},
                ),
            ),
        ),
        *commands_from_rows(
            "seer_query",
            "精灵、技能与魂印",
            "seer_pet",
            (
                (
                    "seer.pet.query",
                    ("精灵雷伊", "雷伊技能", "雷伊魂印"),
                    "查询精灵、技能和魂印信息",
                    {"show_in_poke": True},
                ),
                (
                    "seer.pet.image",
                    ("雷伊立绘", "雷伊皮肤", "皮肤雷伊"),
                    "查询精灵立绘或皮肤",
                    {},
                ),
            ),
        ),
        *commands_from_rows(
            "seer_query",
            "刻印与宝石",
            "seer_mintmark",
            (
                (
                    "seer.mintmark.query",
                    ("刻印V8", "精灵王刻印", "宝石绝命"),
                    "查询刻印、刻印系列或宝石",
                    {"show_in_poke": True},
                ),
                (
                    "seer.mintmark.rank",
                    ("刻印攻击榜", "六角双攻榜", "特攻双防刻印榜"),
                    "查询刻印数值榜",
                    {},
                ),
            ),
        ),
        *commands_from_rows(
            "seer_query",
            "套装、部件与称号",
            "seer_equipment",
            (
                (
                    "seer.equipment.query",
                    ("典狱套装", "部件漫游者", "称号神话"),
                    "查询套装、部件或称号",
                    {"show_in_poke": True},
                ),
            ),
        ),
        *commands_from_rows(
            "seer_query",
            "属性与异常",
            "seer_type",
            (
                (
                    "seer.type.query",
                    ("属性圣灵", "火战斗属性", "异常中毒"),
                    "查询属性克制或异常状态",
                    {"show_in_poke": True},
                ),
            ),
        ),
        *commands_from_rows(
            "seer_query",
            "巅峰相关",
            "seer_peak",
            (
                (
                    "seer.peak.query",
                    ("竞技池", "专家池", "巅峰投票"),
                    "查询巅峰池和投票信息",
                    {"show_in_poke": True},
                ),
                (
                    "seer.peak.rank",
                    ("竞技套装榜", "狂野称号榜", "竞技精灵月榜"),
                    "查询巅峰套装、称号和精灵榜",
                    {},
                ),
            ),
        ),
        *commands_from_rows(
            "seer_query",
            "群星牌",
            "seer_autocard",
            (
                (
                    "seer.autocard.query",
                    ("群星牌布布种子", "布布种子群星牌", "群星牌卡98"),
                    "查询群星牌资料",
                    {"show_in_poke": True},
                ),
            ),
        ),
        *commands_from_rows(
            "seer_query",
            "数据工具",
            "seer_data",
            (
                (
                    "seer.data.query",
                    ("下周预告", "新增成就", "数据版本", "赛季倒计时"),
                    "查询赛尔数据和赛季信息",
                    {"show_in_poke": True},
                ),
            ),
        ),
    )


def rank_commands() -> tuple[CommandDescriptor, ...]:
    regular_rows = (
        (
            "rank.help",
            "榜单查询",
            ("榜单", "排行榜", "榜单帮助"),
            "查看可用榜单和查询格式",
            {"show_in_poke": True},
        ),
        (
            "rank.global_collection",
            "全服图鉴榜",
            _global_rank_titles(peak=False),
            "查看全服图鉴类榜单；可追加页码、名次、米米号或分数",
            {"show_in_poke": True},
        ),
        (
            "rank.global_peak",
            "全服巅峰段位榜",
            _global_rank_titles(peak=True),
            "查看全服巅峰段位榜；可追加名次或分数",
            {},
        ),
        (
            "rank.sample_collection",
            "样本图鉴榜",
            _local_rank_titles(peak=False),
            "查看机器人样本中的图鉴和收集排行",
            {},
        ),
        (
            "rank.sample_peak",
            "巅峰样本榜",
            _local_rank_titles(peak=True),
            "查看机器人样本中的巅峰段位、胜率和场次排行",
            {},
        ),
    )
    regular = tuple(
        CommandDescriptor(
            id=command_id,
            plugin_id="rank_help",
            section=section,
            examples=examples,
            description=description,
            features_any=("seer_rank",),
            show_in_poke=options.get("show_in_poke", False),
        )
        for command_id, section, examples, description, options in regular_rows
    )
    return (
        *regular,
        *commands_from_rows(
            "rank_help",
            "本群管理",
            "seer_rank",
            (
                (
                    "rank.display_limit",
                    ("/榜单显示 20",),
                    "设置本群榜单默认显示名次",
                    {
                        "access": (CommandAccess("group", "group_manager"),),
                        "show_in_poke": True,
                    },
                ),
            ),
        ),
        *commands_from_rows(
            "rank_help",
            "超级管理员",
            "seer_rank",
            (
                (
                    "rank.sample_status",
                    ("/样本情况",),
                    "查看样本缓存情况",
                    {"access": (CommandAccess(audience="superuser"),)},
                ),
                (
                    "rank.sample_refresh",
                    ("/刷新样本",),
                    "刷新样本缓存",
                    {"access": (CommandAccess(audience="superuser"),)},
                ),
                (
                    "rank.page_status",
                    ("/榜单情况", "/榜单情况 图鉴榜"),
                    "查看全服榜单缓存",
                    {"access": (CommandAccess(audience="superuser"),)},
                ),
                (
                    "rank.page_refresh",
                    ("/刷新榜单", "/刷新榜单 图鉴榜"),
                    "刷新全服榜单缓存",
                    {"access": (CommandAccess(audience="superuser"),)},
                ),
                (
                    "rank.page_batch",
                    ("/缓存榜单 刻印榜 1-100",),
                    "缓存指定全服榜单区间",
                    {"access": (CommandAccess(audience="superuser"),)},
                ),
            ),
        ),
    )
