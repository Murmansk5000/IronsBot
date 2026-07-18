# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: TC001, TC002
"""Pet query matchers."""

from __future__ import annotations

from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.params import Depends
from nonebot.typing import T_State
from seerapi_models import PetORM

from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.utils.parse_arg import parse_string_arg
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..depends import GetPetData, SeerAPISession
from ..group import SeerMatcherGroup, seer_feature_priority, seer_feature_rule
from ..prompt import PromptItem
from . import pet_actions, pet_handlers
from .query_rules import not_fixed_image_command, not_rank_query


async def _handle_pet_image(  # noqa: PLR0913
    matcher: Matcher,
    state: T_State,
    event: Event,
    session: SeerAPISession,
    arg: str = Depends(parse_string_arg),
    items: list[PromptItem[int]] = Depends(pet_actions.create_pet_prompt_items),
) -> None:
    await pet_handlers.handle_pet_image(matcher, event, state, session, arg, items)


async def _handle_pet_info(
    matcher: Matcher,
    state: T_State,
    event: Event,
    arg: str = Depends(parse_string_arg),
    pets: tuple[PetORM, ...] = GetPetData(),
) -> None:
    await pet_handlers.handle_pet_info(matcher, event, state, arg, pets)


def install(group: SeerMatcherGroup) -> None:
    image_matcher = group.on_message(
        policy=CommandPolicy.command("seer_pet_image"),
        rule=seer_feature_rule("seer_pet")
        & startswith_or_endswith(
            prefixes=("立绘", "皮肤", "查询立绘"),
        )
        & not_rank_query
        & not_fixed_image_command
        & no_reply(),
        priority=seer_feature_priority("seer_pet"),
    )
    image_matcher.append_handler(_handle_pet_image)

    info_matcher = group.on_message(
        policy=CommandPolicy.command("seer_pet_info"),
        rule=seer_feature_rule("seer_pet")
        & startswith_or_endswith(
            prefixes=("精灵", "查询精灵信息", "魂印", "技能"),
            suffixes=("查询精灵信息", "魂印", "技能"),
        )
        & not_rank_query
        & not_fixed_image_command
        & no_reply(),
        priority=seer_feature_priority("seer_pet"),
    )
    info_matcher.append_handler(_handle_pet_info)


__all__ = ["install"]
