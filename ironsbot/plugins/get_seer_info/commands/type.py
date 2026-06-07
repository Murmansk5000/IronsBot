# SPDX-License-Identifier: GPL-3.0-or-later
import re

from nonebot.adapters import Event
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.typing import T_State
from nonebot_plugin_saa import Image, MessageFactory
from seerapi_models import ElementTypeORM
from seerapi_models.element_type import TypeCombinationORM
from sqlmodel import select

from ironsbot.plugins.get_seer_info.prompt import (
    Prompt,
    PromptItem,
    enter_prompt,
)
from ironsbot.plugins.seer_data.db import (
    GetTypeCombinationData,
    SQLModelSession,
    TypeCombinationDataGetter,
)
from ironsbot.utils.parse_arg import parse_string_arg
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..depends import SeerAPISession
from ..group import matcher_group
from ..render import render_type_matchup
from ..type_calc import calc_attack_table, calc_defense_table, calc_type_multiplier

__all__ = [
    "calc_attack_table",
    "calc_defense_table",
    "calc_type_multiplier",
]

PROMPT_MAX_ITEMS = 20
_MAX_CUSTOM_TYPES = 2
_NORMAL_TYPE_ID = 8
_NORMAL_TYPE_MESSAGE = "普通系不支持属性克制表查询，李在赣神魔"
# 自定义属性组合分隔符翻译表
_CUSTOM_SEPARATOR_TRANSLATION = str.maketrans(
    {
        "\uff0b": "+",
        "\uff0f": "/",
        "\uff5c": "|",
        "，": ",",
        "、": ",",
    }
)
# 自定义属性组合分隔符正则表达式
_CUSTOM_TYPE_SPLIT_PATTERN = re.compile(r"[+,/|\s]+")

type_matcher = matcher_group.on_message(
    rule=startswith_or_endswith("属性") & no_reply()
)


async def _build_type_message(
    type_combination: TypeCombinationORM,
    *,
    session: SQLModelSession | None = None,
    cache_key: str | None = None,
) -> MessageFactory:
    pic_bytes = await render_type_matchup(
        type_combination,
        session=session,
        cache_key=cache_key,
    )
    msg = MessageFactory()
    msg += Image(pic_bytes)
    return msg


def _contains_normal_type(type_combination: TypeCombinationORM) -> bool:
    return _NORMAL_TYPE_ID in {
        type_combination.primary_id,
        type_combination.secondary_id,
    }


def _split_custom_type_names(arg: str, all_names: set[str]) -> tuple[str, ...] | None:
    normalized = arg.translate(_CUSTOM_SEPARATOR_TRANSLATION).strip()
    result: tuple[str, ...] | None = None
    if not normalized:
        return result

    parts = tuple(part for part in _CUSTOM_TYPE_SPLIT_PATTERN.split(normalized) if part)
    if len(parts) == 1:
        token = parts[0]
        if token in all_names:
            result = (token,)
        else:
            candidates: list[tuple[str, str]] = []
            for i in range(1, len(token)):
                left, right = token[:i], token[i:]
                if left not in all_names or right not in all_names:
                    continue
                candidate = (left, right)
                if candidate not in candidates:
                    candidates.append(candidate)
            if len(candidates) == 1:
                result = candidates[0]
    elif (
        len(parts) == _MAX_CUSTOM_TYPES
        and all(part in all_names for part in parts)
        and parts[0] != parts[1]
    ):
        result = parts
    return result


def _parse_custom_type_combination(
    session: SQLModelSession,
    arg: str,
) -> tuple[TypeCombinationORM, str] | None:
    all_types = session.exec(select(ElementTypeORM)).all()
    if not all_types:
        return None

    name_to_type: dict[str, ElementTypeORM] = {tp.name: tp for tp in all_types}
    type_names = _split_custom_type_names(arg, set(name_to_type))
    if type_names is None:
        return None

    elements = [name_to_type[name] for name in type_names]
    secondary_id = elements[1].id if len(elements) == _MAX_CUSTOM_TYPES else None
    custom_name = "".join(element.name for element in elements)
    custom_combo = TypeCombinationORM(
        id=-1,
        name=f"{custom_name}（DIY 属性）",
        name_en="custom",
        primary_id=elements[0].id,
        secondary_id=secondary_id,
    )

    if secondary_id is None:
        cache_key = f"custom_type_matchup_{elements[0].id}"
    else:
        lower, upper = sorted((elements[0].id, secondary_id))
        cache_key = f"custom_type_matchup_{lower}_{upper}"

    return custom_combo, cache_key


async def _type_prompt_resolver(
    item: PromptItem[int],
    matcher: Matcher,
    session: SQLModelSession,
) -> None:
    type_combination = TypeCombinationDataGetter.get(session, item.value)
    if type_combination is None:
        await matcher.finish(
            f"❌未找到属性 {item.value}（这是一个bug，请反馈给开发者）"
        )

    if _contains_normal_type(type_combination):
        await matcher.finish(_NORMAL_TYPE_MESSAGE)

    msg = await _build_type_message(type_combination)
    await msg.send()


@type_matcher.handle()
async def handle_type(
    matcher: Matcher,
    state: T_State,
    event: Event,
    session: SeerAPISession,
    type_combinations: tuple[TypeCombinationORM, ...] = GetTypeCombinationData(),
) -> None:
    if not type_combinations:
        parsed = _parse_custom_type_combination(session, parse_string_arg(state))
        if parsed is None:
            raise FinishedException

        custom_combo, cache_key = parsed
        if _contains_normal_type(custom_combo):
            await matcher.finish(_NORMAL_TYPE_MESSAGE)

        msg = await _build_type_message(
            custom_combo,
            session=session,
            cache_key=cache_key,
        )
        await msg.finish()

    if len(type_combinations) == 1:
        if _contains_normal_type(type_combinations[0]):
            await matcher.finish(_NORMAL_TYPE_MESSAGE)

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
        _type_prompt_resolver,
    )
