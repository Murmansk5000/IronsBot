# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: TC001, TC002
"""Upstream type query matchers."""

from __future__ import annotations

from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.typing import T_State

from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..depends import SeerAPISession
from ..group import matcher_group, seer_feature_priority, seer_feature_rule
from ..upstream_commands import effect as upstream_effect
from ..upstream_commands import type as upstream_type
from .upstream_query_common import UPSTREAM_QUERY_PLUGIN_NAME, dispatch_plugin

type_matcher = matcher_group.on_message(
    rule=seer_feature_rule("seer_type")
    & startswith_or_endswith("属性")
    & no_reply(),
    priority=seer_feature_priority("seer_type"),
)


@type_matcher.handle()
async def _handle_type(
    matcher: Matcher,
    state: T_State,
    event: Event,
    session: SeerAPISession,
    type_combinations: tuple[
        upstream_type.TypeCombinationORM,
        ...,
    ] = upstream_type.GetTypeCombinationData(),
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="type",
        session=session,
        type_combinations=type_combinations,
    )

battle_effect_matcher = matcher_group.on_message(
    rule=seer_feature_rule("seer_type")
    & startswith_or_endswith(
        ("异常", "查询异常状态"),
        suffixes="异常",
    )
    & no_reply(),
    priority=seer_feature_priority("seer_type"),
)


@battle_effect_matcher.handle()
async def _handle_battle_effect(
    matcher: Matcher,
    event: Event,
    state: T_State,
    battle_effects: tuple[
        upstream_effect.BattleEffectORM,
        ...,
    ] = upstream_effect.GetBattleEffectData(),
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="battle_effect",
        battle_effects=battle_effects,
    )
