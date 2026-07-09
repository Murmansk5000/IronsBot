# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.exception import FinishedException

from ..depends import PetDataGetter
from ..prompt import Prompt, PromptItem, enter_prompt, simple_prompt_resolver
from ..upstream_commands import pet as upstream_pet
from . import pet_actions
from .upstream_help import finish_query_help

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.matcher import Matcher
    from seerapi_models import PetORM

    from ironsbot.shared.plugin_system import PluginContext

    from ..depends import SeerAPISession


async def handle_pet_image(
    matcher: Matcher,
    event: Event,
    context: PluginContext,
) -> None:
    state = context.state
    if state is None:
        return
    session: SeerAPISession = context.data["session"]
    arg = str(context.data.get("arg", ""))
    items: list[PromptItem[int]] = context.data["items"]

    if not arg.strip():
        await finish_query_help(matcher, event, "skin")

    if not items:
        raise FinishedException

    if len(items) == 1:
        msg = await pet_actions.build_pet_image_message(items[0], session)
        await msg.finish()

    if len(items) > upstream_pet.PROMPT_MAX_ITEMS:
        if len(arg) == 1:
            for item in items:
                if item.name == arg:
                    msg = await pet_actions.build_pet_image_message(item, session)
                    await msg.finish()

        await matcher.finish(
            f"重名超过{upstream_pet.PROMPT_MAX_ITEMS}个，请重新检索关键词："
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
    context: PluginContext,
) -> None:
    state = context.state
    if state is None:
        return
    arg = str(context.data.get("arg", ""))
    pets: tuple[PetORM, ...] = context.data["pets"]

    if not arg.strip():
        await finish_query_help(matcher, event, "pet")

    if not pets:
        raise FinishedException

    if len(pets) == 1:
        msg = await pet_actions.build_pet_info_message(pets[0])
        await msg.finish()

    if len(pets) > upstream_pet.PROMPT_MAX_ITEMS:
        if len(arg) == 1:
            for pet in pets:
                if pet.name == arg:
                    msg = await pet_actions.build_pet_info_message(pet)
                    await msg.finish()

        await matcher.finish(
            f"重名超过{upstream_pet.PROMPT_MAX_ITEMS}个，请重新检索关键词："
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
