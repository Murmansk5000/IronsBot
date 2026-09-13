# SPDX-License-Identifier: MIT
"""Platform-neutral command contracts for the Seer query domain."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.command_catalog import (
    CommandContract,
    commands_from_rows,
    parsed_command_input_matcher,
)
from ironsbot.core.player_reference_commands import player_reference_input_matcher
from ironsbot.services.seer.countermark_stat_rank_parsing import (
    parse_countermark_stat_rank_command,
)
from ironsbot.services.seer.data_query_commands import (
    DATA_QUERY_COMMANDS,
    DATA_QUERY_HELP_EXAMPLES,
    NEW_CONTENT_COMMAND_SPECS,
    NEW_CONTENT_COMMANDS,
)
from ironsbot.services.seer.peak import (
    PEAK_EXPERT_POOL_COMMANDS,
    PEAK_MASTER_POOL_COMMANDS,
    PEAK_PET_RANK_COMMANDS,
    PEAK_POOL_COMMANDS,
    PEAK_QUERY_COMMANDS,
    PEAK_RANK_COMMANDS,
    PEAK_SUIT_RANK_COMMANDS,
    PEAK_TITLE_RANK_COMMANDS,
    PEAK_VOTE_COMMANDS,
)
from ironsbot.services.seer.query_commands import (
    AUTOCARD_QUERY,
    BATTLE_EFFECT_QUERY,
    EQUIP_QUERY,
    GEM_QUERY,
    MINTMARK_QUERY,
    SANCTUARY_QUERY,
    SUIT_QUERY,
    TITLE_QUERY,
    TYPE_QUERY,
    pet_image_input,
    pet_query_input,
    team_query_input,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver


def seer_command_contracts(
    player_id_resolver: PlayerIdResolver,
    *,
    image_commands: frozenset[str] = frozenset(),
) -> tuple[CommandContract, ...]:
    player_query_input = player_reference_input_matcher(
        ("米米号", "查询玩家信息"),
        player_id_resolver.has_known_reference,
    )
    player_shortcut_input = player_reference_input_matcher(
        ("收集", "巅峰", "群星牌"),
        player_id_resolver.has_known_reference,
    )
    player_binding_input = player_reference_input_matcher(
        ("绑定米米号",),
        player_id_resolver.has_known_reference,
    )
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
                    {
                        "show_in_poke": True,
                        "routing_matcher": player_query_input,
                    },
                ),
                (
                    "seer.player.default",
                    ("米米号", "收集", "巅峰", "群星牌"),
                    "查询已绑定默认米米号的对应数据；未绑定时使用“米米号+完整米米号”",
                    {"routing_matcher": player_shortcut_input},
                ),
                (
                    "seer.player.bind",
                    ("绑定米米号123456",),
                    "查询并绑定默认米米号，之后可使用快捷查询",
                    {"routing_matcher": player_binding_input},
                ),
                (
                    "seer.player.unbind",
                    ("解绑米米号",),
                    "解除当前账号绑定的默认米米号",
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
                    {
                        "show_in_poke": True,
                        "routing_matcher": parsed_command_input_matcher(
                            team_query_input
                        ),
                    },
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
                    {
                        "show_in_poke": True,
                        "routing_matcher": parsed_command_input_matcher(
                            pet_query_input(image_commands)
                        ),
                    },
                ),
                (
                    "seer.pet.image",
                    ("雷伊立绘", "雷伊皮肤", "皮肤雷伊"),
                    "查询精灵立绘或皮肤",
                    {
                        "routing_matcher": parsed_command_input_matcher(
                            pet_image_input(image_commands)
                        )
                    },
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
                    {
                        "show_in_poke": True,
                        "routing_matcher": parsed_command_input_matcher(
                            lambda text: MINTMARK_QUERY(text) or GEM_QUERY(text)
                        ),
                    },
                ),
                (
                    "seer.mintmark.rank",
                    ("刻印攻击榜", "六角双攻榜", "特攻双防刻印榜"),
                    "查询刻印数值榜",
                    {
                        "routing_matcher": parsed_command_input_matcher(
                            parse_countermark_stat_rank_command
                        )
                    },
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
                    {
                        "show_in_poke": True,
                        "routing_matcher": parsed_command_input_matcher(
                            lambda text: (
                                SUIT_QUERY(text)
                                or EQUIP_QUERY(text)
                                or TITLE_QUERY(text)
                            )
                        ),
                    },
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
                    {
                        "show_in_poke": True,
                        "routing_matcher": parsed_command_input_matcher(
                            lambda text: TYPE_QUERY(text) or BATTLE_EFFECT_QUERY(text)
                        ),
                    },
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
                    (
                        PEAK_POOL_COMMANDS[0],
                        PEAK_EXPERT_POOL_COMMANDS[0],
                        PEAK_MASTER_POOL_COMMANDS[0],
                        PEAK_VOTE_COMMANDS[0],
                    ),
                    "查询巅峰池和投票信息",
                    {
                        "show_in_poke": True,
                        "routing_matcher": lambda text, _context: (
                            text in PEAK_QUERY_COMMANDS
                        ),
                    },
                ),
                (
                    "seer.peak.rank",
                    (
                        PEAK_SUIT_RANK_COMMANDS[0],
                        PEAK_TITLE_RANK_COMMANDS[1],
                        PEAK_PET_RANK_COMMANDS[0],
                    ),
                    "查询巅峰套装、称号和精灵榜",
                    {
                        "routing_matcher": lambda text, _context: (
                            text in PEAK_RANK_COMMANDS
                        )
                    },
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
                    {
                        "show_in_poke": True,
                        "routing_matcher": parsed_command_input_matcher(AUTOCARD_QUERY),
                    },
                ),
                (
                    "seer.autocard.sanctuary",
                    ("群星牌场地", "圣域", "祝印"),
                    "查询群星牌场地和回合祝印效果",
                    {"routing_matcher": parsed_command_input_matcher(SANCTUARY_QUERY)},
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
                    DATA_QUERY_HELP_EXAMPLES,
                    "查询赛尔数据和赛季信息",
                    {
                        "show_in_poke": True,
                        "routing_matcher": lambda text, _context: (
                            text in DATA_QUERY_COMMANDS
                        ),
                    },
                ),
                (
                    "seer.data.new_content",
                    NEW_CONTENT_COMMANDS,
                    "查看本周官方新增内容分类",
                    {},
                ),
                *tuple(
                    (
                        spec.command_id,
                        spec.commands,
                        spec.description,
                        {"features_all": spec.required_features},
                    )
                    for spec in NEW_CONTENT_COMMAND_SPECS
                ),
            ),
        ),
    )
