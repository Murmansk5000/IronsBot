# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Iterable

from nonebot.adapters import Event
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.typing import T_State
from nonebot_plugin_saa import MessageFactory
from seerapi_models import GemCategoryORM, MintmarkClassCategoryORM, MintmarkORM, PetORM
from seerapi_models.common import SixAttributes
from seerapi_models.mintmark import AbilityPartORM, SkillPartORM, UniversalPartORM

from ironsbot.plugins.seer_data.db import (
    GemCategoryDataGetter,
    GetGemCategoryData,
)
from ironsbot.utils import build_sub_line
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..depends import (
    GetMintmarkClassData,
    GetMintmarkData,
    MintmarkBodyImageGetter,
    MintmarkDataGetter,
)
from ..group import matcher_group
from ..prompt import (
    Prompt,
    PromptItem,
    enter_prompt,
    simple_prompt_resolver,
)

mintmark_matcher = matcher_group.on_message(
    rule=startswith_or_endswith("刻印") & no_reply()
)


PROMPT_MAX_ITEMS = 30


def _mark_attributes(mintmark: MintmarkORM) -> SixAttributes | None:
    part = mintmark.ability_part or mintmark.skill_part or mintmark.universal_part
    if isinstance(part, AbilityPartORM):
        attr = part.max_attr_value.to_model()
    elif isinstance(part, UniversalPartORM):
        attr = part.max_attr_value.to_model()
        if part.extra_attr_value:
            attr = attr + part.extra_attr_value.to_model()
    elif isinstance(part, SkillPartORM):
        return None
    else:
        raise TypeError(f"未知的刻印类型: {type(part)}")

    return attr.round()


def _mark_type_description(attributes: SixAttributes | None) -> str:
    strings: list[str] = []
    if attributes is None:
        return ""
    if attributes.atk and not attributes.sp_atk:
        strings.append("物")
    elif attributes.sp_atk and not attributes.atk:
        strings.append("特")
    elif attributes.atk and attributes.sp_atk:
        strings.append("双刀")

    if (attributes.atk >= 54 or attributes.sp_atk >= 54) and attributes.spd < 40:
        strings.append("攻")
    if attributes.spd >= 40:
        strings.append("速")
    if attributes.def_ >= 40 or attributes.sp_def >= 40:
        strings.append("盾")
    if attributes.hp >= 100:
        strings.append("体")

    return "".join(strings)


def _deduplicate(mintmarks: Iterable[MintmarkORM]) -> tuple[MintmarkORM, ...]:
    seen_ids = set()
    result = []
    for mintmark in mintmarks:
        if mintmark.id not in seen_ids:
            result.append(mintmark)
            seen_ids.add(mintmark.id)

    return tuple(result)


def _fmt_attr(label: str, value: float, col_width: int = 8) -> str:
    text = f"-{label}{value}"
    cjk_count = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    display_len = len(text) + cjk_count
    return text + "\u2007" * max(col_width - display_len, 1)


def _build_pet_bind(pet: PetORM) -> str:
    return f"{pet.name}（{pet.id}）"


async def build_mintmark_message(mintmark: MintmarkORM) -> MessageFactory:
    msg = MessageFactory()
    msg += f"💮【{mintmark.name}】\n"
    msg += await MintmarkBodyImageGetter.get(str(mintmark.id))
    msg += f"🆔：{mintmark.id}\n"
    if mintmark.pet:
        if len(mintmark.pet) > 1:
            msg += "绑定精灵：\n"
            msg += build_sub_line(texts=[_build_pet_bind(pet) for pet in mintmark.pet])
        else:
            msg += f"绑定精灵：{_build_pet_bind(mintmark.pet[0])}\n"

    part = mintmark.ability_part or mintmark.skill_part or mintmark.universal_part
    if isinstance(part, UniversalPartORM):
        class_name = part.mintmark_class.name if part.mintmark_class else "无"
        msg += f"系列：{class_name} \n"
    elif isinstance(part, SkillPartORM):
        skills = " | ".join(f"{skill.name}（{skill.id}）" for skill in mintmark.skill)
        msg += f"技能：{skills}\n"
        msg += f"效果：{mintmark.desc}"
        return msg
    elif not isinstance(part, AbilityPartORM):
        raise TypeError(f"未知的刻印类型: {type(part)}")

    if (attr := _mark_attributes(mintmark)) is not None:
        msg += f"数值：(总和{attr.total})\n"
        msg += (
            f"{_fmt_attr('攻击', attr.atk)}"
            f"{_fmt_attr('防御', attr.def_)}"
            f"{_fmt_attr('速度', attr.spd)}\n"
            f"{_fmt_attr('特攻', attr.sp_atk)}"
            f"{_fmt_attr('特防', attr.sp_def)}"
            f"{_fmt_attr('体力', attr.hp)}"
        )
    return msg


def _item_desc_fmt(mintmark: MintmarkORM) -> str:
    attr = _mark_attributes(mintmark)
    if attr is None or not (desc := _mark_type_description(attr)):
        return f"{mintmark.id}"

    return f"{mintmark.id} {desc}"


@mintmark_matcher.handle()
async def handle_mintmark(
    matcher: Matcher,
    state: T_State,
    event: Event,
    mintmarks: tuple[MintmarkORM, ...] = GetMintmarkData(),
    classes: tuple[MintmarkClassCategoryORM, ...] = GetMintmarkClassData(),
) -> None:

    mintmarks = mintmarks + tuple(part.mintmark for c in classes for part in c.mintmark)
    mintmarks = _deduplicate(mintmarks)

    if not mintmarks:
        raise FinishedException

    if len(mintmarks) == 1:
        msg = await build_mintmark_message(mintmarks[0])
        await msg.finish()

    elif len(mintmarks) > PROMPT_MAX_ITEMS:
        await matcher.finish(f"重名超过{PROMPT_MAX_ITEMS}个，请重新检索关键词！")
    prompt = Prompt(
        title="请问你想查询的刻印是……",
        items=[
            PromptItem(
                name=mintmark.name,
                desc=_item_desc_fmt(mintmark),
                value=mintmark.id,
            )
            for mintmark in mintmarks
        ],
    )
    await enter_prompt(
        matcher,
        event,
        state,
        prompt,
        simple_prompt_resolver(MintmarkDataGetter, build_mintmark_message, "刻印"),
    )


gem_matcher = matcher_group.on_message(rule=startswith_or_endswith("宝石") & no_reply())


@gem_matcher.handle()
async def handle_gem(
    matcher: Matcher,
    state: T_State,
    event: Event,
    categories: tuple[GemCategoryORM, ...] = GetGemCategoryData(),
) -> None:
    if not categories:
        raise FinishedException

    if len(categories) == 1:
        msg = await build_gem_message(categories[0])
        await msg.finish()

    elif len(categories) > PROMPT_MAX_ITEMS:
        await matcher.finish(f"重名超过{PROMPT_MAX_ITEMS}个，请重新检索关键词！")

    prompt = Prompt(
        title="请问你想查询的宝石是……",
        items=[
            PromptItem(
                name=category.name,
                desc=f"{category.generation_id}代",
                value=category.id,
            )
            for category in categories
        ],
    )
    await enter_prompt(
        matcher,
        event,
        state,
        prompt,
        simple_prompt_resolver(GemCategoryDataGetter, build_gem_message, "宝石"),
    )


async def build_gem_message(category: GemCategoryORM) -> MessageFactory:
    msg = MessageFactory()
    msg += f"💎以下是{category.name}系列信息：\n"
    gem_info_list = []
    for gem in category.gem:
        effect = " | ".join(f"{effect.info}" for effect in gem.skill_effect_in_use)
        gem_info_list.append(f"【Lv.{gem.level}】 {effect}")
    msg += "\n".join(gem_info_list)
    return msg
