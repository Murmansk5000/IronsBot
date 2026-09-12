# SPDX-License-Identifier: GPL-3.0-or-later
"""Platform-neutral command contracts for Seer rank queries."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.command_catalog import (
    CommandAccess,
    CommandContract,
    commands_from_rows,
    parsed_command_input_matcher,
)
from ironsbot.core.player_reference_commands import is_player_reference_input
from ironsbot.services.seer.rank_catalog import rank_command_names
from ironsbot.services.seer.rank_display import parse_rank_display_limit_command
from ironsbot.services.seer.rank_list_models import (
    GLOBAL_RANKS,
    LOCAL_RANKS,
    RANK_PAGE_OVERVIEW_COMMANDS,
    RANK_SAMPLE_REFRESH_COMMANDS,
    RANK_SAMPLE_STATUS_COMMANDS,
)
from ironsbot.services.seer.rank_list_parsing import (
    parse_rank_cache_batch_command,
    parse_rank_list_command,
    parse_rank_page_cache_refresh_command,
    parse_rank_page_cache_status_command,
    parse_rank_player_target_command,
    parse_rank_score_command,
)

if TYPE_CHECKING:
    from ironsbot.core.command_catalog import CommandContext
    from ironsbot.core.player_reference_commands import PlayerReferenceRecognizer
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver

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


def _matches_rank_query(
    text: str,
    context: CommandContext,
    *,
    kind: str,
    peak: bool,
    reference_is_known: PlayerReferenceRecognizer,
) -> bool:
    listed = parse_rank_list_command(text)
    if listed is not None:
        if listed.kind != kind:
            return False
        return (
            GLOBAL_RANKS[listed.rank_key].peak_season_sub_key
            if kind == "global"
            else LOCAL_RANKS[listed.rank_key].season_limited
        ) is peak
    if kind != "global":
        return False
    scored = parse_rank_score_command(text)
    if scored is not None:
        return GLOBAL_RANKS[scored.rank_key].peak_season_sub_key is peak
    player = parse_rank_player_target_command(text)
    return (
        player is not None
        and player.player_reference is not None
        and GLOBAL_RANKS[player.rank_key].peak_season_sub_key is peak
        and is_player_reference_input(
            player.player_reference, context, reference_is_known
        )
    )


def rank_help_command_contracts(
    player_id_resolver: PlayerIdResolver,
) -> tuple[CommandContract, ...]:
    """Describe rank commands without depending on a chat adapter."""

    regular_rows = (
        (
            "rank.global_collection",
            "全服图鉴榜",
            _global_rank_titles(peak=False),
            "查看全服图鉴类榜单；可追加页码、名次、米米号或分数",
            "global",
            False,
            True,
        ),
        (
            "rank.global_peak",
            "全服巅峰段位榜",
            _global_rank_titles(peak=True),
            "查看全服巅峰段位榜；可追加名次或分数",
            "global",
            True,
            False,
        ),
        (
            "rank.sample_collection",
            "样本图鉴榜",
            _local_rank_titles(peak=False),
            "查看机器人样本中的图鉴和收集排行",
            "local",
            False,
            False,
        ),
        (
            "rank.sample_peak",
            "巅峰样本榜",
            _local_rank_titles(peak=True),
            "查看机器人样本中的巅峰段位、胜率和场次排行",
            "local",
            True,
            False,
        ),
    )
    regular = tuple(
        CommandContract(
            id=command_id,
            plugin_id="rank_help",
            section=section,
            examples=examples,
            description=description,
            features_any=("seer_rank",),
            show_in_poke=show_in_poke,
            routing_matcher=partial(
                _matches_rank_query,
                kind=kind,
                peak=peak,
                reference_is_known=player_id_resolver.has_known_reference,
            ),
        )
        for (
            command_id, section, examples, description, kind, peak, show_in_poke
        ) in regular_rows
    )
    return (
        CommandContract(
            id="rank.help",
            plugin_id="rank_help",
            section="榜单查询",
            examples=RANK_HELP_COMMANDS[:3],
            routing_aliases=RANK_HELP_COMMANDS,
            description="查看可用榜单和查询格式",
            features_any=("seer_rank",),
            show_in_poke=True,
        ),
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
                        "routing_matcher": parsed_command_input_matcher(
                            parse_rank_display_limit_command
                        ),
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
                    RANK_SAMPLE_STATUS_COMMANDS,
                    "查看样本缓存情况",
                    {"access": (CommandAccess(audience="superuser"),)},
                ),
                (
                    "rank.sample_refresh",
                    RANK_SAMPLE_REFRESH_COMMANDS,
                    "刷新样本缓存",
                    {"access": (CommandAccess(audience="superuser"),)},
                ),
                (
                    "rank.page_status",
                    ("/榜单情况", "/榜单情况 图鉴榜"),
                    "查看全服榜单缓存",
                    {
                        "access": (CommandAccess(audience="superuser"),),
                        "routing_matcher": lambda text, _context: (
                            text in RANK_PAGE_OVERVIEW_COMMANDS
                            or parse_rank_page_cache_status_command(text) is not None
                        ),
                    },
                ),
                (
                    "rank.page_refresh",
                    ("/刷新榜单", "/刷新榜单 图鉴榜"),
                    "刷新全服榜单缓存",
                    {
                        "access": (CommandAccess(audience="superuser"),),
                        "routing_matcher": parsed_command_input_matcher(
                            parse_rank_page_cache_refresh_command
                        ),
                    },
                ),
                (
                    "rank.page_batch",
                    ("/缓存榜单 刻印榜 1-100",),
                    "缓存指定全服榜单区间",
                    {
                        "access": (CommandAccess(audience="superuser"),),
                        "routing_matcher": parsed_command_input_matcher(
                            parse_rank_cache_batch_command
                        ),
                    },
                ),
            ),
        ),
    )
