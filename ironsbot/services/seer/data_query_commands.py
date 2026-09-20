# SPDX-License-Identifier: GPL-3.0-or-later
"""Stable text specifications for Seer data query commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.services.seer.new_content import (
    AUTOCARD_NEW_CONTENT_CATEGORIES,
    PEAK_POOL_NEW_CONTENT_CATEGORIES,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.services.seer.new_content import NewContentCategory

WEEKLY_PREVIEW_COMMANDS = ("下周预告",)
DATA_VERSION_COMMANDS = ("数据版本",)
NEW_CONTENT_COMMANDS = (
    "新增内容",
    "新增",
    "每周",
    "内容",
    "本周更新",
    "每周更新",
    "更新内容",
    "内容更新",
)
NEW_ACHIEVEMENTS_COMMANDS = ("新增成就", "每周成就", "本周成就", "更新成就")
NEW_PETS_COMMANDS = ("新增精灵", "每周精灵", "本周精灵", "更新精灵")
PEAK_ENVIRONMENT_CHANGES_COMMANDS = (
    "巅峰环境变化",
    "巅峰变化",
    "巅峰修改",
    "巅峰池改变",
    "巅峰池变化",
    "池子修改",
    "池子改变",
)
NEW_SKINS_COMMANDS = ("新增皮肤", "每周皮肤", "本周皮肤", "更新皮肤")
NEW_SKILLS_COMMANDS = ("新增技能", "每周技能", "本周技能", "更新技能")
NEW_MINTMARKS_COMMANDS = ("新增刻印", "每周刻印", "本周刻印", "更新刻印")
NEW_SUITS_COMMANDS = ("新增套装", "每周套装", "本周套装", "更新套装")
NEW_EQUIPS_COMMANDS = ("新增部件", "每周部件", "本周部件", "更新部件")
NEW_MOUNTS_COMMANDS = ("新增座驾", "每周座驾", "本周座驾", "更新座驾")
NEW_AUTOCARD_CARDS_COMMANDS = (
    "新增群星牌",
    "新增群星牌卡牌",
    "新增卡牌",
    "每周群星牌",
    "本周群星牌",
    "更新群星牌",
)
NEW_AUTOCARD_ROLES_COMMANDS = (
    "新增群星牌角色",
    "每周群星牌角色",
    "本周群星牌角色",
    "更新群星牌角色",
)
NEW_AUTOCARD_SANCTUARIES_COMMANDS = (
    "新增群星牌圣域",
    "新增圣域",
    "每周群星牌圣域",
    "每周圣域",
    "本周群星牌圣域",
    "本周圣域",
    "更新群星牌圣域",
    "更新圣域",
)
SEASON_COUNTDOWN_COMMANDS = ("赛季倒计时", "赛季时间", "赛季结束", "赛季")
DATA_QUERY_COMMANDS = (
    *WEEKLY_PREVIEW_COMMANDS,
    *DATA_VERSION_COMMANDS,
    *SEASON_COUNTDOWN_COMMANDS,
)
DATA_QUERY_HELP_EXAMPLES = (
    WEEKLY_PREVIEW_COMMANDS[0],
    NEW_CONTENT_COMMANDS[0],
    DATA_VERSION_COMMANDS[0],
    SEASON_COUNTDOWN_COMMANDS[0],
)


@dataclass(frozen=True, slots=True)
class NewContentCommandSpec:
    command_id: str
    commands: tuple[str, ...]
    categories: tuple[NewContentCategory, ...]
    description: str
    required_features: tuple[str, ...] = ()


NEW_CONTENT_COMMAND_SPECS = (
    NewContentCommandSpec(
        "seer.data.new_achievement",
        NEW_ACHIEVEMENTS_COMMANDS,
        ("achievement",),
        "查看本周新增成就及关联称号",
    ),
    NewContentCommandSpec(
        "seer.data.new_pet",
        NEW_PETS_COMMANDS,
        ("pet",),
        "查看本周新增精灵",
        ("seer_pet",),
    ),
    NewContentCommandSpec(
        "seer.data.peak_environment_changes",
        PEAK_ENVIRONMENT_CHANGES_COMMANDS,
        PEAK_POOL_NEW_CONTENT_CATEGORIES,
        "查看本周竞技池与专家池变化",
        ("seer_peak", "seer_pet"),
    ),
    NewContentCommandSpec(
        "seer.data.new_skin",
        NEW_SKINS_COMMANDS,
        ("pet_skin",),
        "查看本周新增皮肤及所属精灵",
        ("seer_pet",),
    ),
    NewContentCommandSpec(
        "seer.data.new_skill",
        NEW_SKILLS_COMMANDS,
        ("skill",),
        "查看本周新增或修改的技能及关联精灵",
        ("seer_pet",),
    ),
    NewContentCommandSpec(
        "seer.data.new_mintmark",
        NEW_MINTMARKS_COMMANDS,
        ("mintmark",),
        "查看本周新增刻印",
        ("seer_mintmark",),
    ),
    NewContentCommandSpec(
        "seer.data.new_suit",
        NEW_SUITS_COMMANDS,
        ("suit",),
        "查看本周新增套装",
        ("seer_equipment",),
    ),
    NewContentCommandSpec(
        "seer.data.new_equip",
        NEW_EQUIPS_COMMANDS,
        ("equip",),
        "查看本周新增部件",
        ("seer_equipment",),
    ),
    NewContentCommandSpec(
        "seer.data.new_mount",
        NEW_MOUNTS_COMMANDS,
        ("mount",),
        "查看本周新增座驾",
        ("seer_equipment",),
    ),
    NewContentCommandSpec(
        "seer.data.new_autocard",
        NEW_AUTOCARD_CARDS_COMMANDS,
        AUTOCARD_NEW_CONTENT_CATEGORIES,
        "查看本周新增群星牌卡牌、角色、元素圣域与祝印",
        ("seer_autocard",),
    ),
    NewContentCommandSpec(
        "seer.data.new_autocard_role",
        NEW_AUTOCARD_ROLES_COMMANDS,
        ("autocard_role",),
        "查看本周新增群星牌赛尔角色",
        ("seer_autocard",),
    ),
    NewContentCommandSpec(
        "seer.data.new_autocard_sanctuary_effect",
        NEW_AUTOCARD_SANCTUARIES_COMMANDS,
        ("autocard_sanctuary_effect",),
        "查看本周新增或修改的群星牌元素圣域与祝印",
        ("seer_autocard",),
    ),
)

NEW_CONTENT_CATEGORY_FEATURES: dict[NewContentCategory, tuple[str, ...]] = {
    "achievement": (),
    "pet": ("seer_pet",),
    "peak_pool": ("seer_pet",),
    "peak_expert_pool": ("seer_pet",),
    "peak_master_pool": ("seer_peak", "seer_pet"),
    "pet_skin": ("seer_pet",),
    "skill": ("seer_pet",),
    "mintmark": ("seer_mintmark",),
    "suit": ("seer_equipment",),
    "equip": ("seer_equipment",),
    "mount": ("seer_equipment",),
    "autocard_card": ("seer_autocard",),
    "autocard_role": ("seer_autocard",),
    "autocard_sanctuary_effect": ("seer_autocard",),
}


def available_new_content_categories(
    feature_is_allowed: Callable[[str], bool],
) -> tuple[NewContentCategory, ...]:
    """Return release categories allowed by the current feature policy."""

    from ironsbot.services.seer.new_content import NEW_CONTENT_CATEGORIES

    return tuple(
        category
        for category in NEW_CONTENT_CATEGORIES
        if all(
            feature_is_allowed(feature)
            for feature in NEW_CONTENT_CATEGORY_FEATURES[category]
        )
    )
