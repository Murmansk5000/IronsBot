# SPDX-License-Identifier: MIT
"""Shared entity query grammars used by the catalog and platform adapters."""

from __future__ import annotations

from functools import partial

from ironsbot.core.affix_commands import AffixArgument, AffixCommand
from ironsbot.core.commands import normalize_command_text
from ironsbot.services.seer.autocard import (
    AUTOCARD_QUERY_PREFIXES,
    AUTOCARD_QUERY_SUFFIXES,
)
from ironsbot.services.seer.autocard_sanctuary import SANCTUARY_QUERY_PREFIXES
from ironsbot.services.seer.query_guards import is_rank_query_text
from ironsbot.services.seer.team import SeerTeamQueryService


def is_reserved_query(text: str, *, image_commands: frozenset[str]) -> bool:
    return normalize_command_text(text) in image_commands or is_rank_query_text(text)


def pet_query_input(image_commands: frozenset[str] = frozenset()) -> AffixCommand:
    return AffixCommand(
        ("精灵", "查询精灵信息", "魂印", "技能"),
        ("查询精灵信息", "魂印", "技能"),
        reject=partial(is_reserved_query, image_commands=image_commands),
    )


def pet_image_input(image_commands: frozenset[str] = frozenset()) -> AffixCommand:
    affixes = ("立绘", "皮肤", "查询立绘")
    return AffixCommand(
        affixes,
        affixes,
        reject=partial(is_reserved_query, image_commands=image_commands),
    )


def pet_avatar_input(image_commands: frozenset[str] = frozenset()) -> AffixCommand:
    return AffixCommand(
        ("头像",),
        ("头像",),
        reject=partial(is_reserved_query, image_commands=image_commands),
    )


MINTMARK_QUERY = AffixCommand(("刻印",), ("刻印",), reject=is_rank_query_text)
GEM_QUERY = AffixCommand(("宝石",), ("宝石",))
SUIT_QUERY = AffixCommand(
    ("套装", "查询套装信息"), ("套装",), reject=is_rank_query_text
)
EQUIP_QUERY = AffixCommand(
    ("部件", "查询部件信息"), ("部件",), reject=is_rank_query_text
)
TITLE_QUERY = AffixCommand(
    ("称号", "查询称号信息"), ("称号",), reject=is_rank_query_text
)
TYPE_QUERY = AffixCommand(("属性",), ("属性",))
BATTLE_EFFECT_QUERY = AffixCommand(("异常", "查询异常状态"), ("异常",))
AUTOCARD_QUERY = AffixCommand(
    AUTOCARD_QUERY_PREFIXES, AUTOCARD_QUERY_SUFFIXES, reject=is_rank_query_text
)
SANCTUARY_QUERY = AffixCommand(SANCTUARY_QUERY_PREFIXES, ())
_TEAM_QUERY = AffixCommand(("战队", "查询战队信息"), ())


def team_query_input(text: str) -> AffixArgument | None:
    parsed = _TEAM_QUERY(text)
    return (
        parsed
        if parsed is not None and SeerTeamQueryService.parse_team_ids(parsed.argument)
        else None
    )
