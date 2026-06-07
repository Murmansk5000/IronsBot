# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.typing import T_State
from nonebot_plugin_saa import MessageFactory
from nonebot_plugin_saa.abstract_factories import FinishedException
from seerapi_models import EquipORM, SuitORM, TitlePartORM

from ironsbot.plugins.seer_data.db import (
    EquipDataGetter,
    GetEquipData,
    GetSuitData,
    GetTitleData,
    SuitDataGetter,
    TitleDataGetter,
)
from ironsbot.plugins.seer_data.image import (
    EquipImageGetter,
    SuitImageGetter,
    TitleImageGetter,
)
from ironsbot.utils import build_sub_line
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..group import matcher_group
from ..prompt import (
    Prompt,
    PromptItem,
    enter_prompt,
    simple_prompt_resolver,
)

suit_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(("套装", "查询套装信息"), suffixes="套装") & no_reply()
)


EQUIP_PART_TYPE_MAP = {
    0: "头部",
    1: "眼部",
    2: "腰部",
    3: "手部",
    4: "脚部",
    5: "背景",
    6: "星际座驾",
}


async def _build_suit_message(suit: SuitORM) -> MessageFactory:
    msg = MessageFactory()
    msg += await SuitImageGetter.get(str(suit.id))
    msg += f"【{suit.name}】\n"
    msg += f"🆔：{suit.id}\n"
    msg += "部件：\n"
    equips = []
    for equip in suit.equips:
        text = f"{EQUIP_PART_TYPE_MAP[equip.part_type.id]}：{equip.name}（{equip.id}）"
        if equip.bonus:
            text += f"\n    效果：{equip.bonus.desc}"
        equips.append(text)

    msg += build_sub_line(texts=equips)
    bonus_desc = suit.bonus.desc if suit.bonus else "无"
    msg += f"套装效果：{bonus_desc}"
    return msg


PROMPT_MAX_ITEMS = 20


@suit_matcher.handle()
async def handle_suit(
    matcher: Matcher,
    state: T_State,
    event: Event,
    suits: tuple[SuitORM, ...] = GetSuitData(),
) -> None:
    if not suits:
        raise FinishedException

    if len(suits) == 1:
        msg = await _build_suit_message(suits[0])
        await msg.finish()

    elif len(suits) > PROMPT_MAX_ITEMS:
        await matcher.finish(f"重名超过{PROMPT_MAX_ITEMS}个，请重新检索关键词！")

    prompt = Prompt(
        title="请问你想查询的套装是……",
        items=[
            PromptItem(name=suit.name, desc=str(suit.id), value=suit.id)
            for suit in suits
        ],
    )
    await enter_prompt(
        matcher,
        event,
        state,
        prompt,
        simple_prompt_resolver(SuitDataGetter, _build_suit_message, "套装"),
    )


equip_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(("部件", "查询部件信息"), suffixes="部件") & no_reply()
)


async def _build_equip_message(equip: EquipORM) -> MessageFactory:
    msg = MessageFactory()
    msg += await EquipImageGetter.get(str(equip.id))
    msg += f"【{equip.name}】\n"
    msg += f"🆔：{equip.id}\n"
    msg += f"部件类型：{EQUIP_PART_TYPE_MAP[equip.part_type.id]}\n"
    if equip.suit:
        msg += f"所属套装：{equip.suit.name}（{equip.suit.id}）\n"
    bonus_desc = equip.bonus.desc if equip.bonus else "无"
    msg += f"效果：{bonus_desc}"
    return msg


@equip_matcher.handle()
async def handle_equip(
    matcher: Matcher,
    state: T_State,
    event: Event,
    equips: tuple[EquipORM, ...] = GetEquipData(),
) -> None:
    if not equips:
        raise FinishedException

    if len(equips) == 1:
        msg = await _build_equip_message(equips[0])
        await msg.finish()

    elif len(equips) > PROMPT_MAX_ITEMS:
        await matcher.finish(f"重名超过{PROMPT_MAX_ITEMS}个，请重新检索关键词！")

    prompt = Prompt(
        title="请问你想查询的装备部件是……",
        items=[
            PromptItem(name=equip.name, desc=str(equip.id), value=equip.id)
            for equip in equips
        ],
    )
    await enter_prompt(
        matcher,
        event,
        state,
        prompt,
        simple_prompt_resolver(EquipDataGetter, _build_equip_message, "装备部件"),
    )


title_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(("称号", "查询称号信息"), suffixes="称号") & no_reply()
)


async def _build_title_message(title: TitlePartORM) -> MessageFactory:
    msg = MessageFactory()
    msg += await TitleImageGetter.get(str(title.id))
    msg += f"【{title.name}】\n"
    msg += f"🆔：{title.id}"
    if title.ability_desc:
        msg += f"\n效果：{title.ability_desc}"
    return msg


@title_matcher.handle()
async def handle_title(
    matcher: Matcher,
    state: T_State,
    event: Event,
    titles: tuple[TitlePartORM, ...] = GetTitleData(),
) -> None:
    if not titles:
        raise FinishedException

    if len(titles) == 1:
        msg = await _build_title_message(titles[0])
        await msg.finish()

    elif len(titles) > PROMPT_MAX_ITEMS:
        await matcher.finish(f"重名超过{PROMPT_MAX_ITEMS}个，请重新检索关键词！")

    prompt = Prompt(
        title="请问你想查询的称号是……",
        items=[
            PromptItem(name=title.name, desc=str(title.id), value=title.id)
            for title in titles
        ],
    )
    await enter_prompt(
        matcher,
        event,
        state,
        prompt,
        simple_prompt_resolver(TitleDataGetter, _build_title_message, "称号"),
    )
