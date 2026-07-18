# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: TC001, TC002
"""Pet query matchers."""

from __future__ import annotations

from functools import partial

from nonebot.adapters import Event
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.params import Depends
from nonebot.typing import T_State
from seerapi_models import PetORM

from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.services.seer.render_cache import RenderCache
from ironsbot.utils.parse_arg import parse_string_arg
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..depends import GetPetData, PetDataGetter, SeerAPISession
from ..group import SeerMatcherGroup, seer_feature_rule
from ..prompt import Prompt, PromptItem, enter_prompt, simple_prompt_resolver
from . import pet_actions
from .query_rules import not_fixed_image_command, not_rank_query


async def _handle_pet_image(  # noqa: PLR0913
    matcher: Matcher,
    state: T_State,
    event: Event,
    session: SeerAPISession,
    arg: str = Depends(parse_string_arg),
    items: list[PromptItem[int]] = Depends(pet_actions.create_pet_prompt_items),
) -> None:
    if not arg.strip() or not items:
        raise FinishedException

    if len(items) == 1:
        message = await pet_actions.build_pet_image_message(items[0], session)
        await message.finish()

    if len(items) > pet_actions.PET_PROMPT_MAX_ITEMS:
        if len(arg) == 1:
            for item in items:
                if item.name == arg:
                    message = await pet_actions.build_pet_image_message(item, session)
                    await message.finish()
        await matcher.finish(
            f"重名超过{pet_actions.PET_PROMPT_MAX_ITEMS}个，请重新检索关键词："
        )

    await enter_prompt(
        matcher,
        event,
        state,
        Prompt(title="请问你想查询的立绘是……", items=items),
        pet_actions.pet_image_resolver,
    )


async def _handle_pet_info(  # noqa: PLR0913
    cache: RenderCache,
    matcher: Matcher,
    state: T_State,
    event: Event,
    arg: str = Depends(parse_string_arg),
    pets: tuple[PetORM, ...] = GetPetData(),
) -> None:
    if not arg.strip() or not pets:
        raise FinishedException

    build_message = partial(pet_actions.build_pet_info_message, cache)
    if len(pets) == 1:
        message = await build_message(pets[0])
        await message.finish()

    if len(pets) > pet_actions.PET_PROMPT_MAX_ITEMS:
        if len(arg) == 1:
            for pet in pets:
                if pet.name == arg:
                    message = await build_message(pet)
                    await message.finish()
        await matcher.finish(
            f"重名超过{pet_actions.PET_PROMPT_MAX_ITEMS}个，请重新检索关键词："
        )

    prompt = Prompt(
        title="请问你想查询的精灵是……",
        items=[
            PromptItem(name=pet.name, desc=str(pet.id), value=pet.id) for pet in pets
        ],
    )
    await enter_prompt(
        matcher,
        event,
        state,
        prompt,
        simple_prompt_resolver(PetDataGetter, build_message, "精灵"),
    )


def install(group: SeerMatcherGroup) -> None:
    image_matcher = group.on_message(
        policy=CommandPolicy.command("seer_pet_image"),
        rule=seer_feature_rule(group.resources.features, "seer_pet")
        & startswith_or_endswith(
            prefixes=("立绘", "皮肤", "查询立绘"),
        )
        & not_rank_query
        & not_fixed_image_command
        & no_reply(),
        priority=group.matcher_priority("seer_pet"),
    )
    image_matcher.append_handler(_handle_pet_image)

    info_matcher = group.on_message(
        policy=CommandPolicy.command("seer_pet_info"),
        rule=seer_feature_rule(group.resources.features, "seer_pet")
        & startswith_or_endswith(
            prefixes=("精灵", "查询精灵信息", "魂印", "技能"),
            suffixes=("查询精灵信息", "魂印", "技能"),
        )
        & not_rank_query
        & not_fixed_image_command
        & no_reply(),
        priority=group.matcher_priority("seer_pet"),
    )
    info_matcher.append_handler(
        partial(_handle_pet_info, group.resources.render_cache)
    )
