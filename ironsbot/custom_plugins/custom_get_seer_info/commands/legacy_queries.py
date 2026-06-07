# SPDX-License-Identifier: GPL-3.0-or-later
"""Custom high-priority entry points for upstream Seer info queries.

These matchers keep upstream query behavior available through the custom plugin
without editing the upstream plugin code. They intentionally reuse upstream
handlers and renderers, while registering at the custom plugin priority so they
win before the original matchers.
"""

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

from .._upstream.commands import cloth as upstream_cloth
from .._upstream.commands import effect as upstream_effect
from .._upstream.commands import mintmark as upstream_mintmark
from .._upstream.commands import other as upstream_other
from .._upstream.commands import peak as upstream_peak
from .._upstream.commands import pet as upstream_pet
from .._upstream.commands import type as upstream_type
from .._upstream.depends import (
    GetPetData,
    PetDataGetter,
    SeerAPISession,
)
from .._upstream.prompt import (
    Prompt,
    PromptItem,
    enter_prompt,
    simple_prompt_resolver,
)
from ..group import matcher_group
from ..render import render_pet_info
from ._skin_price import format_skin_price_lines

pet_image_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(
        prefixes=("立绘", "皮肤", "查询立绘"),
    )
    & no_reply()
)


@pet_image_matcher.handle()
async def _handle_pet_image(  # noqa: PLR0913
    matcher: Matcher,
    state: T_State,
    event: Event,
    session: SeerAPISession,
    arg: str = Depends(parse_string_arg),
    items: list[PromptItem[int]] = Depends(upstream_pet._create_prompt_items),
) -> None:
    if not items:
        raise FinishedException

    if len(items) == 1:
        msg = await _build_pet_image_message(items[0], session)
        await msg.finish()

    if len(items) > upstream_pet.PROMPT_MAX_ITEMS:
        if len(arg) == 1:
            for item in items:
                if item.name == arg:
                    msg = await _build_pet_image_message(item, session)
                    await msg.finish()

        await matcher.finish(
            f"重名超过{upstream_pet.PROMPT_MAX_ITEMS}个，请重新检索关键词！"
        )

    prompt = Prompt(title="请问你想查询的立绘是……", items=items)
    await enter_prompt(matcher, event, state, prompt, _pet_image_resolver)


async def _build_pet_image_message(
    item: PromptItem[int],
    session: SQLModelSession,
):
    msg = await upstream_pet.build_pet_image_message(item, session)
    model = session.exec(
        select(PetSkinORM).where(PetSkinORM.resource_id == item.value)
    ).first()
    if model is None:
        return msg

    msg += await format_skin_price_lines(
        model.id,
        existing_card_price=model.card_price,
    )
    return msg


async def _pet_image_resolver(
    item: PromptItem[int],
    _: Matcher,
    session: SQLModelSession,
) -> None:
    msg = await _build_pet_image_message(item, session)
    await msg.send()

pet_info_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(
        prefixes=("精灵", "查询精灵信息", "魂印", "技能"),
        suffixes=("查询精灵信息", "魂印", "技能"),
    )
    & no_reply()
)


@pet_info_matcher.handle()
async def _handle_pet_info(
    matcher: Matcher,
    state: T_State,
    event: Event,
    arg: str = Depends(parse_string_arg),
    pets: tuple[PetORM, ...] = GetPetData(),
) -> None:
    if not pets:
        raise FinishedException

    if len(pets) == 1:
        msg = await _build_pet_info_message(pets[0])
        await msg.finish()

    if len(pets) > upstream_pet.PROMPT_MAX_ITEMS:
        if len(arg) == 1:
            for pet in pets:
                if pet.name == arg:
                    msg = await _build_pet_info_message(pet)
                    await msg.finish()

        await matcher.finish(
            f"重名超过{upstream_pet.PROMPT_MAX_ITEMS}个，请重新检索关键词！"
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
        simple_prompt_resolver(PetDataGetter, _build_pet_info_message, "精灵"),
    )


async def _build_pet_info_message(pet: PetORM) -> MessageFactory:
    pic_bytes = await render_pet_info(pet)
    msg = MessageFactory()
    msg += Image(pic_bytes)
    return msg

mintmark_matcher = matcher_group.on_message(
    rule=startswith_or_endswith("刻印") & no_reply()
)
mintmark_matcher.handle()(upstream_mintmark.handle_mintmark)

gem_matcher = matcher_group.on_message(
    rule=startswith_or_endswith("宝石") & no_reply()
)
gem_matcher.handle()(upstream_mintmark.handle_gem)

type_matcher = matcher_group.on_message(
    rule=startswith_or_endswith("属性") & no_reply()
)
type_matcher.handle()(upstream_type.handle_type)

battle_effect_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(
        ("异常", "查询异常状态"),
        suffixes="异常",
    )
    & no_reply()
)
battle_effect_matcher.handle()(upstream_effect.handle_battle_effect)

suit_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(
        ("套装", "查询套装信息"),
        suffixes="套装",
    )
    & no_reply()
)
suit_matcher.handle()(upstream_cloth.handle_suit)

equip_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(
        ("部件", "查询部件信息"),
        suffixes="部件",
    )
    & no_reply()
)
equip_matcher.handle()(upstream_cloth.handle_equip)

title_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(
        ("称号", "查询称号信息"),
        suffixes="称号",
    )
    & no_reply()
)
title_matcher.handle()(upstream_cloth.handle_title)

peak_pool_matcher = matcher_group.on_fullmatch(
    ("竞技池", "巅峰竞技池", "竞技精灵池", "限制池"),
    rule=no_reply(),
)
peak_pool_matcher.handle()(upstream_peak.handle_peak_pool)

peak_expert_pool_matcher = matcher_group.on_fullmatch(
    ("专家池", "巅峰专家池", "专家禁用池"),
    rule=no_reply(),
)
peak_expert_pool_matcher.handle()(upstream_peak.handle_peak_expert_pool)

peak_vote_matcher = matcher_group.on_fullmatch(
    ("巅峰投票", "巅峰票选", "巅峰池票选", "竞技池票选", "限制池票选"),
    rule=no_reply(),
)
peak_vote_matcher.handle()(upstream_peak.handle_peak_vote)

peak_suit_matcher = matcher_group.on_fullmatch(
    ("竞技套装榜", "狂野套装榜", "专家套装榜"),
    rule=no_reply(),
)
peak_suit_matcher.handle()(upstream_peak.handle_peak_suit)

peak_title_matcher = matcher_group.on_fullmatch(
    ("竞技称号榜", "狂野称号榜", "专家称号榜"),
    rule=no_reply(),
)
peak_title_matcher.handle()(upstream_peak.handle_title)

peak_pet_matcher = matcher_group.on_fullmatch(
    (
        "竞技精灵月榜",
        "狂野精灵月榜",
        "专家精灵月榜",
        "竞技精灵总榜",
        "狂野精灵总榜",
        "专家精灵总榜",
    ),
    rule=no_reply(),
)
peak_pet_matcher.handle()(upstream_peak.handle_peak_pet)

peak_user_matcher = matcher_group.on_fullmatch(
    ("竞技段位榜", "狂野段位榜", "专家段位榜"),
    rule=no_reply(),
)
peak_user_matcher.handle()(upstream_peak.handle_peak_user)

preview_matcher = matcher_group.on_fullmatch("下周预告", rule=no_reply())
preview_matcher.handle()(upstream_other.handle_preview)

data_version_matcher = matcher_group.on_fullmatch("数据版本", rule=no_reply())
data_version_matcher.handle()(upstream_other.handle_data_version)
