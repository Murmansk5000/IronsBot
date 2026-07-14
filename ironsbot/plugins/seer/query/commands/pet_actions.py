# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot import logger
from nonebot_plugin_saa import Image, MessageFactory
from seerapi_models import PetORM, PetSkinORM
from sqlmodel import select

from ironsbot.integrations.seer_data.image import PetBodyImageGetter
from ironsbot.services.seer.render_crash_report import render_crash_marker
from ironsbot.services.seer.rendering.custom_pet_info import render_custom_pet_info
from ironsbot.services.seer.skin_price import format_skin_price_lines

from ..depends import GetPetData, GetPetSkinData
from ..prompt import PromptItem

if TYPE_CHECKING:
    from nonebot.matcher import Matcher

    from ironsbot.integrations.seer_data.sessions import SQLModelSession



PET_PROMPT_MAX_ITEMS = 20


def create_pet_prompt_items(
    pets: tuple[PetORM, ...] = GetPetData(),
    skins: tuple[PetSkinORM, ...] = GetPetSkinData(),
) -> list[PromptItem[int]]:
    resource_ids: set[int] = set()
    items: list[PromptItem[int]] = []
    for pet in pets:
        if pet.id in resource_ids:
            continue
        resource_ids.add(pet.id)
        items.append(PromptItem(name=pet.name, desc=str(pet.id), value=pet.id))
        for skin in pet.skins:
            if skin.resource_id in resource_ids:
                continue
            resource_ids.add(skin.resource_id)
            items.append(
                PromptItem(
                    name=skin.name,
                    desc=str(skin.resource_id),
                    value=skin.resource_id,
                    is_sub_prompt=True,
                )
            )

    for skin in skins:
        if skin.resource_id in resource_ids:
            continue
        resource_ids.add(skin.resource_id)
        items.append(
            PromptItem(
                name=skin.name,
                desc=f"所属精灵：{skin.pet.name}",
                value=skin.resource_id,
            )
        )
    return items


async def build_pet_image_message(
    item: PromptItem[int],
    session: SQLModelSession,
) -> MessageFactory:
    msg = MessageFactory()
    msg += await PetBodyImageGetter.get(str(item.value))
    msg += f"💎【{item.name}】\n"
    model = session.exec(
        select(PetSkinORM).where(PetSkinORM.resource_id == item.value)
    ).first()
    if model is None:
        return msg

    series_name = "无"
    if model.series:
        series_name = model.series.name
        if model.sub_type:
            series_name += f" - {model.sub_type.name}"

    msg += f"所属精灵：{model.pet.name}\n"
    msg += f"所属系列：{series_name}\n"
    if model.card_price:
        msg += f"礼卡价格：{model.card_price}\n"
    msg += format_skin_price_lines(
        session,
        model.id,
        existing_card_price=model.card_price,
    )
    return msg


async def pet_image_resolver(
    item: PromptItem[int],
    _: Matcher,
    session: SQLModelSession,
) -> None:
    msg = await build_pet_image_message(item, session)
    await msg.send()


async def build_pet_info_message(pet: PetORM) -> MessageFactory:
    logger.info(
        "rendering pet info image: pet_id={} pet_name={} resource_id={}",
        pet.id,
        pet.name,
        pet.resource_id,
    )
    with render_crash_marker(
        operation="pet_info_render",
        pet_id=pet.id,
        pet_name=pet.name,
        resource_id=pet.resource_id,
    ):
        pic_bytes = await render_custom_pet_info(pet)
    logger.info(
        "rendered pet info image: pet_id={} pet_name={} bytes={}",
        pet.id,
        pet.name,
        len(pic_bytes),
    )
    msg = MessageFactory()
    msg += Image(pic_bytes)
    return msg
