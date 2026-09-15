# SPDX-License-Identifier: MIT
"""Shared entity query grammars used by the catalog and platform adapters."""

from __future__ import annotations

import re
from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.affix_commands import AffixArgument, AffixCommand
from ironsbot.core.commands import normalize_command_text
from ironsbot.core.player_reference_commands import is_player_reference_input
from ironsbot.services.seer.autocard import (
    AUTOCARD_QUERY_PREFIXES,
    AUTOCARD_QUERY_SUFFIXES,
)
from ironsbot.services.seer.autocard_sanctuary import SANCTUARY_QUERY_PREFIXES
from ironsbot.services.seer.query_guards import is_rank_query_text

if TYPE_CHECKING:
    from ironsbot.core.command_catalog import CommandContext
    from ironsbot.core.player_reference_commands import (
        PlayerReferenceInputMatcher,
        PlayerReferenceRecognizer,
    )


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


def team_query_argument(text: str) -> AffixArgument | None:
    return _TEAM_QUERY(text)


def team_query_input_matcher(
    reference_is_known: PlayerReferenceRecognizer,
) -> PlayerReferenceInputMatcher:
    def matches(text: str, context: CommandContext) -> bool:
        parsed = team_query_argument(text)
        if parsed is None:
            return False
        reference = parsed.argument.strip()
        if context.has_member_mentions:
            return not reference
        if re.fullmatch(r"\d+(?:\s+\d+)*", reference):
            return True
        if reference.startswith("米米号"):
            reference = reference.removeprefix("米米号").strip()
        return bool(reference) and is_player_reference_input(
            reference,
            context,
            reference_is_known,
        )

    return matches
