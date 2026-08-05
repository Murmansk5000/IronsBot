# SPDX-License-Identifier: GPL-3.0-or-later
"""Platform-neutral command contracts for Seer rank queries."""

from __future__ import annotations

from ironsbot.runtime.commands import (
    CommandAccess,
    CommandDescriptor,
    commands_from_rows,
)
from ironsbot.services.seer.rank_catalog import rank_command_names
from ironsbot.services.seer.rank_list_models import GLOBAL_RANKS, LOCAL_RANKS

RANK_HELP_COMMANDS = (
    "榜单",
    "排行榜",
    "榜单帮助",
    "排行榜帮助",
    "有哪些榜单",
    "可用榜单",
)


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


def rank_help_command_descriptors() -> tuple[CommandDescriptor, ...]:
    """Describe rank commands without depending on a chat adapter."""

    regular_rows = (
        (
            "rank.help",
            "榜单查询",
            RANK_HELP_COMMANDS[:3],
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
