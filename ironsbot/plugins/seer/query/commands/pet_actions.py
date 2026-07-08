# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot import logger
from nonebot_plugin_saa import Image, MessageFactory
from seerapi_models import PetORM, PetSkinORM
from sqlmodel import select

from ironsbot.services.seer.render_crash_report import render_crash_marker
from ironsbot.services.seer.rendering.custom_pet_info import render_custom_pet_info
from ironsbot.services.seer.skin_price import format_skin_price_lines

from ..upstream_commands import pet as upstream_pet

if TYPE_CHECKING:
    from nonebot.matcher import Matcher

    from ironsbot.integrations.seer_data.db import SQLModelSession

    from ..prompt import PromptItem


async def build_pet_image_message(
    item: PromptItem[int],
    session: SQLModelSession,
) -> MessageFactory:
    msg = await upstream_pet.build_pet_image_message(item, session)
    model = session.exec(
        select(PetSkinORM).where(PetSkinORM.resource_id == item.value)
    ).first()
    if model is None:
        return msg

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
