# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.exception import FinishedException

from ..depends import PetDataGetter
from ..prompt import Prompt, PromptItem, enter_prompt, simple_prompt_resolver
from . import pet_actions
from .upstream_help import finish_query_help

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.matcher import Matcher
    from nonebot.typing import T_State
    from seerapi_models import PetORM

    from ..depends import SeerAPISession


async def handle_pet_image(  # noqa: PLR0913
    matcher: Matcher,
    event: Event,
    state: T_State,
    session: SeerAPISession,
    arg: str,
    items: list[PromptItem[int]],
) -> None:
    if not arg.strip():
        await finish_query_help(matcher, event, "skin")

    if not items:
        raise FinishedException

    if len(items) == 1:
        msg = await pet_actions.build_pet_image_message(items[0], session)
        await msg.finish()

    if len(items) > pet_actions.PET_PROMPT_MAX_ITEMS:
        if len(arg) == 1:
            for item in items:
                if item.name == arg:
                    msg = await pet_actions.build_pet_image_message(item, session)
                    await msg.finish()

        await matcher.finish(
            f"重名超过{pet_actions.PET_PROMPT_MAX_ITEMS}个，请重新检索关键词："
        )

    prompt = Prompt(title="请问你想查询的立绘是……", items=items)
    await enter_prompt(
        matcher,
        event,
        state,
        prompt,
        pet_actions.pet_image_resolver,
    )


async def handle_pet_info(
    matcher: Matcher,
    event: Event,
    state: T_State,
    arg: str,
    pets: tuple[PetORM, ...],
) -> None:
    if not arg.strip():
        await finish_query_help(matcher, event, "pet")

    if not pets:
        raise FinishedException

    if len(pets) == 1:
        msg = await pet_actions.build_pet_info_message(pets[0])
        await msg.finish()

    if len(pets) > pet_actions.PET_PROMPT_MAX_ITEMS:
        if len(arg) == 1:
            for pet in pets:
                if pet.name == arg:
                    msg = await pet_actions.build_pet_info_message(pet)
                    await msg.finish()

        await matcher.finish(
            f"重名超过{pet_actions.PET_PROMPT_MAX_ITEMS}个，请重新检索关键词："
        )

    prompt = Prompt(
        title="请问你想查询的精灵是……",
        items=[
            PromptItem(name=pet.name, desc=str(pet.id), value=pet.id)
            for pet in pets
        ],
    )
    await enter_prompt(
        matcher,
        event,
        state,
        prompt,
        simple_prompt_resolver(
            PetDataGetter,
            pet_actions.build_pet_info_message,
            "精灵",
        ),
    )


__all__ = ["handle_pet_image", "handle_pet_info"]
