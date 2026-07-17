# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from nonebot.adapters import Event
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.typing import T_State
from nonebot_plugin_saa import MessageFactory
from seerapi_models import GemCategoryORM, MintmarkClassCategoryORM, MintmarkORM, PetORM
from seerapi_models.common import SixAttributes
from seerapi_models.mintmark import AbilityPartORM, SkillPartORM, UniversalPartORM

from ironsbot.integrations.seer_data.getters import GemCategoryDataGetter
from ironsbot.utils import build_sub_line

from ..config import get_mintmark_query_config
from ..depends import (
    MintmarkBodyImageGetter,
    MintmarkDataGetter,
)
from ..prompt import (
    Prompt,
    PromptItem,
    enter_prompt,
    simple_prompt_resolver,
)

PROMPT_MAX_ITEMS = 30
ATTACK_MARK_THRESHOLD = 54
SPEED_MARK_THRESHOLD = 40
DEFENSE_MARK_THRESHOLD = 40
HP_MARK_THRESHOLD = 100


@dataclass(frozen=True, slots=True)
class MintmarkQueryView:
    mintmark: MintmarkORM
    related_ids: tuple[int, ...] = ()

    @property
    def ids(self) -> tuple[int, ...]:
        return (self.mintmark.id, *self.related_ids)


class UnknownMintmarkTypeError(TypeError):
    def __init__(self, part: object) -> None:
        super().__init__(f"未知的刻印类型: {type(part)}")


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
        raise UnknownMintmarkTypeError(part)

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
        strings.append("双攻")

    if (
        attributes.atk >= ATTACK_MARK_THRESHOLD
        or attributes.sp_atk >= ATTACK_MARK_THRESHOLD
    ):
        strings.append("攻")
    if attributes.spd >= SPEED_MARK_THRESHOLD:
        strings.append("速")
    if (
        attributes.def_ >= DEFENSE_MARK_THRESHOLD
        or attributes.sp_def >= DEFENSE_MARK_THRESHOLD
    ):
        strings.append("盾")
    if attributes.hp >= HP_MARK_THRESHOLD:
        strings.append("体")

    return "".join(strings)


def _connected_mintmarks(mintmark: MintmarkORM) -> dict[int, MintmarkORM]:
    result: dict[int, MintmarkORM] = {}
    pending = [mintmark]
    while pending:
        current = pending.pop()
        if current.id in result:
            continue
        result[current.id] = current

        part = current.universal_part
        connected = getattr(part, "connect", None) if part is not None else None
        if isinstance(connected, MintmarkORM):
            pending.append(connected)
        for connected_part in current.connected_universal_parts:
            child = getattr(connected_part, "mintmark", None)
            if isinstance(child, MintmarkORM):
                pending.append(child)
    return result


def _preferred_connected_mintmark(
    mintmarks: dict[int, MintmarkORM],
) -> MintmarkORM:
    connected_children = [
        mintmark
        for mintmark in mintmarks.values()
        if mintmark.universal_part is not None
        and mintmark.universal_part.connect_id is not None
    ]
    return max(connected_children or list(mintmarks.values()), key=lambda item: item.id)


def _build_mintmark_views(
    mintmarks: Iterable[MintmarkORM],
) -> tuple[MintmarkQueryView, ...]:
    unique = {mintmark.id: mintmark for mintmark in mintmarks}
    if not unique:
        return ()

    if not get_mintmark_query_config().merge_connected:
        return tuple(
            MintmarkQueryView(
                mintmark=mintmark,
                related_ids=tuple(
                    sorted(
                        related_id
                        for related_id in _connected_mintmarks(mintmark)
                        if related_id != mintmark.id
                    )
                ),
            )
            for mintmark in unique.values()
        )

    result: list[MintmarkQueryView] = []
    seen_ids: set[int] = set()
    for mintmark in unique.values():
        if mintmark.id in seen_ids:
            continue
        connected = _connected_mintmarks(mintmark)
        seen_ids.update(connected)
        preferred = _preferred_connected_mintmark(connected)
        result.append(
            MintmarkQueryView(
                mintmark=preferred,
                related_ids=tuple(
                    sorted(
                        related_id
                        for related_id in connected
                        if related_id != preferred.id
                    )
                ),
            )
        )
    return tuple(result)


def _fmt_attr(label: str, value: float, col_width: int = 8) -> str:
    text = f"-{label}{value}"
    cjk_count = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    display_len = len(text) + cjk_count
    return text + "\u2007" * max(col_width - display_len, 1)


def _build_pet_bind(pet: PetORM) -> str:
    return f"{pet.name}（{pet.id}）"


async def build_mintmark_message(
    item: MintmarkQueryView | MintmarkORM,
) -> MessageFactory:
    view = item if isinstance(item, MintmarkQueryView) else MintmarkQueryView(item)
    mintmark = view.mintmark
    msg = MessageFactory()
    msg += f"💮【{mintmark.name}】\n"
    msg += await MintmarkBodyImageGetter.get(str(mintmark.id))
    id_text = "、".join(str(mintmark_id) for mintmark_id in view.ids)
    if not get_mintmark_query_config().merge_connected and view.related_ids:
        related_text = "、".join(str(mintmark_id) for mintmark_id in view.related_ids)
        id_text = f"{mintmark.id}（关联{related_text}）"
    msg += f"🆔：{id_text}\n"
    if mintmark.pet:
        if len(mintmark.pet) > 1:
            msg += "绑定精灵：\n"
            msg += build_sub_line(texts=[_build_pet_bind(pet) for pet in mintmark.pet])
        else:
            msg += f"绑定精灵：{_build_pet_bind(mintmark.pet[0])}\n"

    part = mintmark.ability_part or mintmark.skill_part or mintmark.universal_part
    if isinstance(part, UniversalPartORM):
        if part.mintmark_class:
            class_name = f"{part.mintmark_class.name}（ID：{part.mintmark_class.id}）"
        else:
            class_name = "无"
        msg += f"系列：{class_name} \n"
    elif isinstance(part, SkillPartORM):
        skills = " | ".join(f"{skill.name}（{skill.id}）" for skill in mintmark.skill)
        msg += f"技能：{skills}\n"
        msg += f"效果：{mintmark.desc}"
        return msg
    elif not isinstance(part, AbilityPartORM):
        raise UnknownMintmarkTypeError(part)

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


def _item_desc_fmt(item: MintmarkQueryView) -> str:
    mintmark = item.mintmark
    attr = _mark_attributes(mintmark)
    desc = _mark_type_description(attr) if attr is not None else ""
    if get_mintmark_query_config().merge_connected:
        id_text = "、".join(str(mintmark_id) for mintmark_id in item.ids)
        return " ".join(part for part in (id_text, desc) if part)

    related_text = "、".join(str(mintmark_id) for mintmark_id in item.related_ids)
    parts = [str(mintmark.id)]
    if related_text:
        parts.append(f"关联{related_text}")
    if desc:
        parts.append(desc)
    return "，".join(parts)


async def _resolve_mintmark_prompt(
    item: PromptItem[int],
    matcher: Matcher,
    session: Any,
) -> None:
    mintmark = MintmarkDataGetter.get(session, item.value)
    if mintmark is None:
        await matcher.finish(
            f"❌未找到刻印 {item.value}（这是一个bug，请反馈给开发者）"
        )
    views = _build_mintmark_views((mintmark,))
    if not views:
        await matcher.finish(
            f"❌未找到刻印 {item.value}（这是一个bug，请反馈给开发者）"
        )
    msg = await build_mintmark_message(views[0])
    await msg.send()


async def handle_mintmark(
    matcher: Matcher,
    state: T_State,
    event: Event,
    mintmarks: tuple[MintmarkORM, ...],
    classes: tuple[MintmarkClassCategoryORM, ...],
) -> None:

    mintmarks = mintmarks + tuple(part.mintmark for c in classes for part in c.mintmark)
    views = _build_mintmark_views(mintmarks)

    if not views:
        raise FinishedException

    if len(views) == 1:
        msg = await build_mintmark_message(views[0])
        await msg.finish()

    elif len(views) > PROMPT_MAX_ITEMS:
        await matcher.finish(f"重名超过{PROMPT_MAX_ITEMS}个，请重新检索关键词！")
    prompt = Prompt(
        title="请问你想查询的刻印是……",
        items=[
            PromptItem(
                name=view.mintmark.name,
                desc=_item_desc_fmt(view),
                value=view.mintmark.id,
            )
            for view in views
        ],
    )
    await enter_prompt(
        matcher,
        event,
        state,
        prompt,
        _resolve_mintmark_prompt,
    )


async def handle_gem(
    matcher: Matcher,
    state: T_State,
    event: Event,
    categories: tuple[GemCategoryORM, ...],
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
