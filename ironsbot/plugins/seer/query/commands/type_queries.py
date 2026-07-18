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
from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..depends import SeerAPISession
from ..group import SeerMatcherGroup, seer_feature_rule
from . import battle_effect_handlers, type_handlers


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


def install(group: SeerMatcherGroup) -> None:
    type_matcher = group.on_message(
        policy=CommandPolicy.command("seer_type_query"),
        rule=seer_feature_rule(group.resources.features, "seer_type")
        & startswith_or_endswith("属性")
        & no_reply(),
        priority=group.matcher_priority("seer_type"),
    )
    type_matcher.append_handler(_handle_type)

    effect_matcher = group.on_message(
        policy=CommandPolicy.command("seer_battle_effect_query"),
        rule=seer_feature_rule(group.resources.features, "seer_type")
        & startswith_or_endswith(
            ("异常", "查询异常状态"),
            suffixes="异常",
        )
        & no_reply(),
        priority=group.matcher_priority("seer_type"),
    )
    effect_matcher.append_handler(_handle_battle_effect)
