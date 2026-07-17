# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: TC002
"""Upstream equipment query matchers."""

from __future__ import annotations

from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.typing import T_State

from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..group import matcher_group, seer_feature_priority, seer_feature_rule
from ..upstream_commands import cloth as upstream_cloth
from .query_rules import not_rank_query

suit_matcher = matcher_group.on_message(
    rule=seer_feature_rule("seer_equipment")
    & startswith_or_endswith(
        ("套装", "查询套装信息"),
        suffixes="套装",
    )
    & not_rank_query
    & no_reply(),
    priority=seer_feature_priority("seer_equipment"),
)


@suit_matcher.handle()
async def _handle_suit(
    matcher: Matcher,
    state: T_State,
    event: Event,
    suits: tuple[
        upstream_cloth.SuitORM,
        ...,
    ] = upstream_cloth.GetSuitData(),
) -> None:
    await upstream_cloth.handle_suit(
        matcher=matcher,
        state=state,
        event=event,
        suits=suits,
    )

equip_matcher = matcher_group.on_message(
    rule=seer_feature_rule("seer_equipment")
    & startswith_or_endswith(
        ("部件", "查询部件信息"),
        suffixes="部件",
    )
    & not_rank_query
    & no_reply(),
    priority=seer_feature_priority("seer_equipment"),
)


@equip_matcher.handle()
async def _handle_equip(
    matcher: Matcher,
    state: T_State,
    event: Event,
    equips: tuple[
        upstream_cloth.EquipORM,
        ...,
    ] = upstream_cloth.GetEquipData(),
) -> None:
    await upstream_cloth.handle_equip(
        matcher=matcher,
        state=state,
        event=event,
        equips=equips,
    )

title_matcher = matcher_group.on_message(
    rule=seer_feature_rule("seer_equipment")
    & startswith_or_endswith(
        ("称号", "查询称号信息"),
        suffixes="称号",
    )
    & not_rank_query
    & no_reply(),
    priority=seer_feature_priority("seer_equipment"),
)


@title_matcher.handle()
async def _handle_title(
    matcher: Matcher,
    state: T_State,
    event: Event,
    titles: tuple[
        upstream_cloth.TitlePartORM,
        ...,
    ] = upstream_cloth.GetTitleData(),
) -> None:
    await upstream_cloth.handle_title(
        matcher=matcher,
        state=state,
        event=event,
        titles=titles,
    )
