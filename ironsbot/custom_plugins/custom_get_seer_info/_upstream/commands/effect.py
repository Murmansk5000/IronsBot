# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.adapters import Event
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.typing import T_State
from nonebot_plugin_saa import MessageFactory
from seerapi_models import BattleEffectORM

from ..prompt import (
    Prompt,
    PromptItem,
    enter_prompt,
    simple_prompt_resolver,
)
from ironsbot.plugins.seer_data.db import (
    BattleEffectDataGetter,
    GetBattleEffectData,
)
from ironsbot.plugins.seer_data.image import BattleEffectImageGetter
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..group import matcher_group

battle_effect_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(("异常", "查询异常状态"), suffixes="异常") & no_reply()
)


async def _build_battle_effect_message(
    battle_effect: BattleEffectORM,
) -> MessageFactory:
    msg = MessageFactory()
    msg += await BattleEffectImageGetter.get(str(battle_effect.id))
    msg += f"【{battle_effect.name}（ID：{battle_effect.id}）】\n"
    msg += f"类型：{'，'.join(t.name for t in battle_effect.type) or '无'}\n"
    msg += f"抗性类型：{battle_effect.resistance.name if battle_effect.resistance else '无'}\n"
    msg += f"效果：{battle_effect.desc}"
    return msg


PROMPT_MAX_ITEMS = 20


@battle_effect_matcher.handle()
async def handle_battle_effect(
    matcher: Matcher,
    event: Event,
    state: T_State,
    battle_effects: tuple[BattleEffectORM, ...] = GetBattleEffectData(),
) -> None:
    if not battle_effects:
        raise FinishedException
    if len(battle_effects) == 1:
        msg = await _build_battle_effect_message(battle_effects[0])
        await msg.finish()
    elif len(battle_effects) > PROMPT_MAX_ITEMS:
        await matcher.finish(f"重名超过{PROMPT_MAX_ITEMS}个，请重新检索关键词！")

    prompt = Prompt(
        title="请问你想查询的异常状态是……",
        items=[
            PromptItem(
                name=battle_effect.name,
                desc=str(battle_effect.id),
                value=battle_effect.id,
            )
            for battle_effect in battle_effects
        ],
    )
    await enter_prompt(
        matcher,
        event,
        state,
        prompt,
        simple_prompt_resolver(
            BattleEffectDataGetter, _build_battle_effect_message, "异常状态"
        ),
    )
