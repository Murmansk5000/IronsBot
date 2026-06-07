# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.adapters import Event
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.params import Depends
from nonebot.typing import T_State
from nonebot_plugin_saa import Image, MessageFactory
from seerapi_models import PetORM, PetSkinORM
from sqlmodel import select

from ironsbot.plugins.seer_data.db import SQLModelSession
from ironsbot.utils.parse_arg import parse_string_arg
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..depends import (
    GetPetData,
    GetPetSkinData,
    PetBodyImageGetter,
    PetDataGetter,
    SeerAPISession,
)
from ..group import matcher_group
from ..prompt import (
    Prompt,
    PromptItem,
    enter_prompt,
    simple_prompt_resolver,
)
from ..render import render_pet_info

pet_image_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(
        prefixes=("立绘", "皮肤", "查询立绘"),
    )
    & no_reply()
)


PROMPT_MAX_ITEMS = 20


def _create_prompt_items(
    pets: tuple[PetORM, ...] = GetPetData(),
    skins: tuple[PetSkinORM, ...] = GetPetSkinData(),
) -> list[PromptItem[int]]:
    id_set: set[int] = set()
    prompt_items: list[PromptItem[int]] = []
    for pet in pets:
        if pet.id in id_set:
            continue
        id_set.add(pet.id)
        prompt_items.append(PromptItem(name=pet.name, desc=str(pet.id), value=pet.id))
        for skin in pet.skins:
            if skin.resource_id in id_set:
                continue
            id_set.add(skin.resource_id)
            prompt_items.append(
                PromptItem(
                    name=skin.name,
                    desc=str(skin.resource_id),
                    value=skin.resource_id,
                    is_sub_prompt=True,
                )
            )

    for skin in skins:
        if skin.resource_id in id_set:
            continue
        id_set.add(skin.resource_id)
        prompt_items.append(
            PromptItem(
                name=skin.name,
                desc=f"所属精灵：{skin.pet.name}",
                value=skin.resource_id,
            )
        )
    return prompt_items


@pet_image_matcher.handle()
async def handle_pet_image(
    matcher: Matcher,
    state: T_State,
    event: Event,
    session: SeerAPISession,
    arg: str = Depends(parse_string_arg),
    items: list[PromptItem[int]] = Depends(_create_prompt_items),
) -> None:
    if not items:
        raise FinishedException

    if len(items) == 1:
        msg = await build_pet_image_message(items[0], session)
        await msg.finish()

    if len(items) > PROMPT_MAX_ITEMS:
        if len(arg) == 1:
            for item in items:
                if item.name == arg:
                    msg = await build_pet_image_message(item, session)
                    await msg.finish()

        await matcher.finish(f"重名超过{PROMPT_MAX_ITEMS}个，请重新检索关键词！")

    prompt = Prompt(title="请问你想查询的立绘是……", items=items)
    await enter_prompt(matcher, event, state, prompt, pet_image_resolver)


async def build_pet_image_message(
    args: PromptItem[int], session: SQLModelSession
) -> MessageFactory:
    msg = MessageFactory()
    resource_id = args.value
    image = await PetBodyImageGetter.get(str(resource_id))
    msg += image
    msg += f"💎【{args.name}】\n"
    if (
        model := session.exec(
            select(PetSkinORM).where(PetSkinORM.resource_id == resource_id)
        ).first()
    ) is None:
        return msg

    def build_series_name() -> str:
        if not model.series:
            return "无"

        series_name = model.series.name
        if model.sub_type:
            series_name += f" - {model.sub_type.name}"

        return series_name

    msg += f"所属精灵：{model.pet.name}\n"
    if series_name := build_series_name():
        msg += f"所属系列：{series_name}\n"
    if model.card_price:
        msg += f"礼卡价格：{model.card_price}\n"

    return msg


async def pet_image_resolver(
    item: PromptItem[int], _: Matcher, session: SQLModelSession
) -> None:
    msg = await build_pet_image_message(item, session)
    await msg.send()


# ============ 精灵信息卡 ============

pet_info_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(
        prefixes=("精灵", "查询精灵信息", "魂印", "技能"),
        suffixes=("查询精灵信息", "魂印", "技能"),
    )
    & no_reply()
)


@pet_info_matcher.handle()
async def handle_pet_info(
    matcher: Matcher,
    state: T_State,
    event: Event,
    arg: str = Depends(parse_string_arg),
    pets: tuple[PetORM, ...] = GetPetData(),
) -> None:
    if not pets:
        raise FinishedException

    if len(pets) == 1:
        msg = await build_pet_info_message(pets[0])
        await msg.finish()

    if len(pets) > PROMPT_MAX_ITEMS:
        if len(arg) == 1:
            for pet in pets:
                if pet.name == arg:
                    msg = await build_pet_info_message(pet)
                    await msg.finish()

        await matcher.finish(f"重名超过{PROMPT_MAX_ITEMS}个，请重新检索关键词！")

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
        simple_prompt_resolver(PetDataGetter, build_pet_info_message, "精灵"),
    )


async def build_pet_info_message(pet: PetORM) -> MessageFactory:
    pic_bytes = await render_pet_info(pet)
    msg = MessageFactory()
    msg += Image(pic_bytes)
    return msg
