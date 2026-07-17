# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: TC001, TC002
"""Element type and battle effect query matchers."""

from __future__ import annotations

from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.typing import T_State
from seerapi_models import BattleEffectORM
from seerapi_models.element_type import TypeCombinationORM

from ironsbot.integrations.seer_data.getters import (
    GetBattleEffectData,
    GetTypeCombinationData,
)
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..depends import SeerAPISession
from ..group import matcher_group, seer_feature_priority, seer_feature_rule
from . import battle_effect_handlers, type_handlers

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
        TypeCombinationORM,
        ...,
    ] = GetTypeCombinationData(),
) -> None:
    await type_handlers.handle_type(
        matcher=matcher,
        state=state,
        event=event,
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
        BattleEffectORM,
        ...,
    ] = GetBattleEffectData(),
) -> None:
    await battle_effect_handlers.handle_battle_effect(
        matcher=matcher,
        state=state,
        event=event,
        battle_effects=battle_effects,
    )
