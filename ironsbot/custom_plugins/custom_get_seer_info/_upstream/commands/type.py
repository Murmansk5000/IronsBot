# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.adapters import Event
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.typing import T_State
from nonebot_plugin_saa import Image, MessageFactory
from seerapi_models.element_type import TypeCombinationORM

from ..prompt import (
    Prompt,
    PromptItem,
    enter_prompt,
    simple_prompt_resolver,
)
from ironsbot.plugins.seer_data.db import (
    GetTypeCombinationData,
    TypeCombinationDataGetter,
)
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..group import matcher_group
from ..render import render_type_matchup
from ..type_calc import calc_attack_table, calc_defense_table, calc_type_multiplier

__all__ = [
    "calc_attack_table",
    "calc_defense_table",
    "calc_type_multiplier",
]

PROMPT_MAX_ITEMS = 20

type_matcher = matcher_group.on_message(
    rule=startswith_or_endswith("属性") & no_reply()
)


async def _build_type_message(type_combination: TypeCombinationORM) -> MessageFactory:
    pic_bytes = await render_type_matchup(type_combination)
    msg = MessageFactory()
    msg += Image(pic_bytes)
    return msg


@type_matcher.handle()
async def handle_type(
    matcher: Matcher,
    state: T_State,
    event: Event,
    type_combinations: tuple[TypeCombinationORM, ...] = GetTypeCombinationData(),
) -> None:
    if not type_combinations:
        raise FinishedException

    if len(type_combinations) == 1:
        msg = await _build_type_message(type_combinations[0])
        await msg.finish()
    elif len(type_combinations) > PROMPT_MAX_ITEMS:
        await matcher.finish(f"重名超过{PROMPT_MAX_ITEMS}个，请重新检索关键词！")

    prompt = Prompt(
        title="请问你想查询的属性是……",
        items=[
            PromptItem(
                name=type_combination.name,
                desc=str(type_combination.id),
                value=type_combination.id,
            )
            for type_combination in type_combinations
        ],
    )
    await enter_prompt(
        matcher,
        event,
        state,
        prompt,
        simple_prompt_resolver(TypeCombinationDataGetter, _build_type_message, "属性"),
    )
