# SPDX-License-Identifier: MIT
"""Platform-neutral command contracts for the Seer query domain."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.runtime.commands import CommandDescriptor, commands_from_rows
from ironsbot.runtime.player_reference_commands import player_reference_input_matcher
from ironsbot.services.seer.data_query_commands import (
    DATA_QUERY_HELP_EXAMPLES,
    NEW_ACHIEVEMENTS_COMMANDS,
    NEW_AUTOCARD_CARDS_COMMANDS,
    NEW_AUTOCARD_ROLES_COMMANDS,
    NEW_AUTOCARD_SANCTUARIES_COMMANDS,
    NEW_CONTENT_COMMANDS,
    NEW_EQUIPS_COMMANDS,
    NEW_MINTMARKS_COMMANDS,
    NEW_MOUNTS_COMMANDS,
    NEW_PETS_COMMANDS,
    NEW_SKILLS_COMMANDS,
    NEW_SKINS_COMMANDS,
    NEW_SUITS_COMMANDS,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver

def seer_command_descriptors(
    player_id_resolver: PlayerIdResolver,
) -> tuple[CommandDescriptor, ...]:
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
                    DATA_QUERY_HELP_EXAMPLES,
                    "查询赛尔数据和赛季信息",
                    {"show_in_poke": True},
                ),
                (
                    "seer.data.new_content",
                    NEW_CONTENT_COMMANDS,
                    "查看本周官方新增内容分类",
                    {},
                ),
                (
                    "seer.data.new_pet",
                    NEW_PETS_COMMANDS,
                    "查看本周新增精灵",
                    {"features_all": ("seer_data", "seer_pet")},
                ),
                (
                    "seer.data.new_skin",
                    NEW_SKINS_COMMANDS,
                    "查看本周新增皮肤及所属精灵",
                    {"features_all": ("seer_data", "seer_pet")},
                ),
                (
                    "seer.data.new_skill",
                    NEW_SKILLS_COMMANDS,
                    "查看本周新增或修改的技能及关联精灵",
                    {"features_all": ("seer_data", "seer_pet")},
                ),
                (
                    "seer.data.new_mintmark",
                    NEW_MINTMARKS_COMMANDS,
                    "查看本周新增刻印",
                    {"features_all": ("seer_data", "seer_mintmark")},
                ),
                (
                    "seer.data.new_suit",
                    NEW_SUITS_COMMANDS,
                    "查看本周新增套装",
                    {"features_all": ("seer_data", "seer_equipment")},
                ),
                (
                    "seer.data.new_equip",
                    NEW_EQUIPS_COMMANDS,
                    "查看本周新增部件",
                    {"features_all": ("seer_data", "seer_equipment")},
                ),
                (
                    "seer.data.new_mount",
                    NEW_MOUNTS_COMMANDS,
                    "查看本周新增座驾",
                    {"features_all": ("seer_data", "seer_equipment")},
                ),
                (
                    "seer.data.new_achievement",
                    NEW_ACHIEVEMENTS_COMMANDS,
                    "查看本周新增成就及关联称号",
                    {},
                ),
                (
                    "seer.data.new_autocard",
                    NEW_AUTOCARD_CARDS_COMMANDS,
                    "查看本周新增群星牌卡牌、角色、元素圣域与祝印",
                    {"features_all": ("seer_data", "seer_autocard")},
                ),
                (
                    "seer.data.new_autocard_role",
                    NEW_AUTOCARD_ROLES_COMMANDS,
                    "查看本周新增群星牌赛尔角色",
                    {"features_all": ("seer_data", "seer_autocard")},
                ),
                (
                    "seer.data.new_autocard_sanctuary_effect",
                    NEW_AUTOCARD_SANCTUARIES_COMMANDS,
                    "查看本周新增或修改的群星牌元素圣域与祝印",
                    {"features_all": ("seer_data", "seer_autocard")},
                ),
            ),
        ),
    )
