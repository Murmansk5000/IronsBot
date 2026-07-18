# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: TC002
"""Equipment query matchers."""

from __future__ import annotations

from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.typing import T_State
from seerapi_models import EquipORM, SuitORM, TitlePartORM

from ironsbot.integrations.seer_data.getters import (
    GetEquipData,
    GetSuitData,
    GetTitleData,
)
from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..group import SeerMatcherGroup, seer_feature_priority, seer_feature_rule
from . import equipment_handlers
from .query_rules import not_rank_query


async def _handle_suit(
    matcher: Matcher,
    state: T_State,
    event: Event,
    suits: tuple[SuitORM, ...] = GetSuitData(),
) -> None:
    await equipment_handlers.handle_suit(
        matcher=matcher,
        state=state,
        event=event,
        suits=suits,
    )


async def _handle_equip(
    matcher: Matcher,
    state: T_State,
    event: Event,
    equips: tuple[EquipORM, ...] = GetEquipData(),
) -> None:
    await equipment_handlers.handle_equip(
        matcher=matcher,
        state=state,
        event=event,
        equips=equips,
    )


async def _handle_title(
    matcher: Matcher,
    state: T_State,
    event: Event,
    titles: tuple[TitlePartORM, ...] = GetTitleData(),
) -> None:
    await equipment_handlers.handle_title(
        matcher=matcher,
        state=state,
        event=event,
        titles=titles,
    )


def install(group: SeerMatcherGroup) -> None:
    suit_matcher = group.on_message(
        policy=CommandPolicy.command("seer_suit_query"),
        rule=seer_feature_rule("seer_equipment")
        & startswith_or_endswith(
            ("套装", "查询套装信息"),
            suffixes="套装",
        )
        & not_rank_query
        & no_reply(),
        priority=seer_feature_priority("seer_equipment"),
    )
    suit_matcher.append_handler(_handle_suit)

    equip_matcher = group.on_message(
        policy=CommandPolicy.command("seer_equipment_query"),
        rule=seer_feature_rule("seer_equipment")
        & startswith_or_endswith(
            ("部件", "查询部件信息"),
            suffixes="部件",
        )
        & not_rank_query
        & no_reply(),
        priority=seer_feature_priority("seer_equipment"),
    )
    equip_matcher.append_handler(_handle_equip)

    title_matcher = group.on_message(
        policy=CommandPolicy.command("seer_title_query"),
        rule=seer_feature_rule("seer_equipment")
        & startswith_or_endswith(
            ("称号", "查询称号信息"),
            suffixes="称号",
        )
        & not_rank_query
        & no_reply(),
        priority=seer_feature_priority("seer_equipment"),
    )
    title_matcher.append_handler(_handle_title)


__all__ = ["install"]
