# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from seerapi_models import GemCategoryORM, MintmarkORM, PetORM
from seerapi_models.mintmark import (
    AbilityPartORM,
    SkillPartORM,
    UniversalPartORM,
)

from ironsbot.services.seer.formatting import format_sub_lines
from ironsbot.services.seer.images import fetch_optional_image
from ironsbot.services.seer.query_result import (
    QueryChoice,
    QueryReply,
    QueryResult,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from seerapi_models.common import SixAttributes

    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.images import SeerImageSource

PROMPT_MAX_ITEMS = 30
ATTACK_MARK_THRESHOLD = 54
SPEED_MARK_THRESHOLD = 40
DEFENSE_MARK_THRESHOLD = 40
HP_MARK_THRESHOLD = 100


@dataclass(frozen=True, slots=True)
class MintmarkQueryView:
    mintmark: MintmarkORM
    related_ids: tuple[int, ...] = ()
    ordered_ids: tuple[int, ...] = ()

    @property
    def ids(self) -> tuple[int, ...]:
        return self.ordered_ids or (self.mintmark.id, *self.related_ids)


@dataclass(frozen=True, slots=True)
class _MintmarkReplyData:
    mintmark_id: int
    name: str
    text: str


class UnknownMintmarkTypeError(TypeError):
    def __init__(self, part: object) -> None:
        super().__init__(f"未知的刻印类型: {type(part)}")


class MintmarkQueryService:
    def __init__(
        self,
        data: SeerDataAccess,
        images: SeerImageSource,
        *,
        merge_connected: bool,
    ) -> None:
        self._data = data
        self._images = images
        self._merge_connected = merge_connected

    async def search_mintmark(self, arg: str) -> QueryResult[int]:
        if not arg.strip():
            return QueryResult()
        with self._data.mintmark_query(arg) as mintmarks:
            views = build_mintmark_views(
                mintmarks,
                merge_connected=self._merge_connected,
            )
            if not views:
                return QueryResult()
            if len(views) == 1:
                reply_data = self._reply_data(views[0])
            elif len(views) > PROMPT_MAX_ITEMS:
                return QueryResult(
                    message=f"重名超过{PROMPT_MAX_ITEMS}个，请重新检索关键词！"
                )
            else:
                return QueryResult(
                    choices=tuple(
                        QueryChoice(
                            view.mintmark.name,
                            format_mintmark_choice_description(
                                view,
                                merge_connected=self._merge_connected,
                            ),
                            view.mintmark.id,
                        )
                        for view in views
                    )
                )
        return QueryResult(reply=await self._build_reply(reply_data))

    async def select_mintmark(self, mintmark_id: int) -> QueryResult[object]:
        with self._data.mintmark_query(str(mintmark_id)) as mintmarks:
            if not mintmarks:
                return QueryResult(
                    message=(
                        f"❌未找到刻印 {mintmark_id}"
                        "（这是一个bug，请反馈给开发者）"
                    )
                )
            views = build_mintmark_views(
                mintmarks,
                merge_connected=self._merge_connected,
            )
            if not views:
                return QueryResult(
                    message=(
                        f"❌未找到刻印 {mintmark_id}"
                        "（这是一个bug，请反馈给开发者）"
                    )
                )
            reply_data = self._reply_data(views[0])
        return QueryResult(reply=await self._build_reply(reply_data))

    async def search_gem(self, arg: str) -> QueryResult[int]:
        with self._data.resolve(self._data.gem_category, arg) as values:
            categories = tuple(values)
            if not categories:
                return QueryResult()
            if len(categories) == 1:
                reply = _gem_reply(categories[0])
            elif len(categories) > PROMPT_MAX_ITEMS:
                return QueryResult(
                    message=f"重名超过{PROMPT_MAX_ITEMS}个，请重新检索关键词！"
                )
            else:
                return QueryResult(
                    choices=tuple(
                        QueryChoice(
                            category.name,
                            f"{category.generation_id}代",
                            category.id,
                        )
                        for category in categories
                    )
                )
        return QueryResult(reply=reply)

    async def select_gem(self, category_id: int) -> QueryResult[object]:
        with self._data.get(
            self._data.gem_category,
            category_id,
        ) as category:
            if category is None:
                return QueryResult(
                    message=(
                        f"❌未找到宝石 {category_id}"
                        "（这是一个bug，请反馈给开发者）"
                    )
                )
            reply = _gem_reply(category)
        return QueryResult(reply=reply)

    def _reply_data(
        self,
        view: MintmarkQueryView,
    ) -> _MintmarkReplyData:
        mintmark = view.mintmark
        return _MintmarkReplyData(
            mintmark_id=int(mintmark.id),
            name=str(mintmark.name),
            text=_format_mintmark_details(
                view,
                merge_connected=self._merge_connected,
            ),
        )

    async def _build_reply(
        self,
        reply_data: _MintmarkReplyData,
    ) -> QueryReply:
        image = await fetch_optional_image(
            self._images,
            "mintmark",
            str(reply_data.mintmark_id),
        )
        return QueryReply(
            leading_text=f"💮【{reply_data.name}】\n",
            text=reply_data.text,
            image=image.data,
            image_error=image.error,
        )


def build_mintmark_views(
    mintmarks: Iterable[MintmarkORM],
    *,
    merge_connected: bool,
) -> tuple[MintmarkQueryView, ...]:
    unique = {mintmark.id: mintmark for mintmark in mintmarks}
    if not unique:
        return ()
    if not merge_connected:
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
                ordered_ids=_ordered_connected_mintmark_ids(connected),
            )
        )
    return tuple(result)


def format_mintmark_choice_description(
    view: MintmarkQueryView,
    *,
    merge_connected: bool,
) -> str:
    attributes = _mark_attributes(view.mintmark)
    description = (
        _mark_type_description(attributes)
        if attributes is not None
        else ""
    )
    if merge_connected:
        id_text = "、".join(str(mintmark_id) for mintmark_id in view.ids)
        return " ".join(part for part in (id_text, description) if part)
    related_text = "、".join(
        str(mintmark_id) for mintmark_id in view.related_ids
    )
    parts = [str(view.mintmark.id)]
    if related_text:
        parts.append(f"关联{related_text}")
    if description:
        parts.append(description)
    return "，".join(parts)


def _format_mintmark_details(
    view: MintmarkQueryView,
    *,
    merge_connected: bool,
) -> str:
    mintmark = view.mintmark
    id_text = "、".join(str(mintmark_id) for mintmark_id in view.ids)
    if not merge_connected and view.related_ids:
        related = "、".join(
            str(mintmark_id) for mintmark_id in view.related_ids
        )
        id_text = f"{mintmark.id}（关联{related}）"
    text = f"🆔：{id_text}\n"
    if mintmark.pet:
        if len(mintmark.pet) > 1:
            text += "绑定精灵：\n"
            text += format_sub_lines(_format_pet(pet) for pet in mintmark.pet)
        else:
            text += f"绑定精灵：{_format_pet(mintmark.pet[0])}\n"
    part = mintmark.ability_part or mintmark.skill_part or mintmark.universal_part
    if isinstance(part, UniversalPartORM):
        class_name = (
            f"{part.mintmark_class.name}（ID：{part.mintmark_class.id}）"
            if part.mintmark_class
            else "无"
        )
        text += f"系列：{class_name} \n"
    elif isinstance(part, SkillPartORM):
        skills = " | ".join(
            f"{skill.name}（{skill.id}）" for skill in mintmark.skill
        )
        return text + f"技能：{skills}\n效果：{mintmark.desc}"
    elif not isinstance(part, AbilityPartORM):
        raise UnknownMintmarkTypeError(part)
    attributes = _mark_attributes(mintmark)
    if attributes is None:
        return text
    return (
        text
        + f"数值：(总和{attributes.total})\n"
        + f"{_format_attribute('攻击', attributes.atk)}"
        + f"{_format_attribute('防御', attributes.def_)}"
        + f"{_format_attribute('速度', attributes.spd)}\n"
        + f"{_format_attribute('特攻', attributes.sp_atk)}"
        + f"{_format_attribute('特防', attributes.sp_def)}"
        + _format_attribute("体力", attributes.hp)
    )


def _mark_attributes(mintmark: MintmarkORM) -> SixAttributes | None:
    part = mintmark.ability_part or mintmark.skill_part or mintmark.universal_part
    if isinstance(part, AbilityPartORM):
        attributes = part.max_attr_value.to_model()
    elif isinstance(part, UniversalPartORM):
        attributes = part.max_attr_value.to_model()
        if part.extra_attr_value:
            attributes = attributes + part.extra_attr_value.to_model()
    elif isinstance(part, SkillPartORM):
        return None
    else:
        raise UnknownMintmarkTypeError(part)
    return attributes.round()


def _mark_type_description(attributes: SixAttributes | None) -> str:
    if attributes is None:
        return ""
    parts: list[str] = []
    if attributes.atk and not attributes.sp_atk:
        parts.append("物")
    elif attributes.sp_atk and not attributes.atk:
        parts.append("特")
    elif attributes.atk and attributes.sp_atk:
        parts.append("双攻")
    if (
        attributes.atk >= ATTACK_MARK_THRESHOLD
        or attributes.sp_atk >= ATTACK_MARK_THRESHOLD
    ):
        parts.append("攻")
    if attributes.spd >= SPEED_MARK_THRESHOLD:
        parts.append("速")
    if (
        attributes.def_ >= DEFENSE_MARK_THRESHOLD
        or attributes.sp_def >= DEFENSE_MARK_THRESHOLD
    ):
        parts.append("盾")
    if attributes.hp >= HP_MARK_THRESHOLD:
        parts.append("体")
    return "".join(parts)


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
    children = [
        mintmark
        for mintmark in mintmarks.values()
        if mintmark.universal_part is not None
        and mintmark.universal_part.connect_id is not None
    ]
    return max(children or list(mintmarks.values()), key=lambda item: item.id)


def _ordered_connected_mintmark_ids(
    mintmarks: dict[int, MintmarkORM],
) -> tuple[int, ...]:
    children_by_parent: dict[int, list[int]] = {}
    root_ids: list[int] = []
    for mintmark in mintmarks.values():
        part = mintmark.universal_part
        parent_id = None if part is None else part.connect_id
        if parent_id is None or parent_id not in mintmarks:
            root_ids.append(mintmark.id)
            continue
        children_by_parent.setdefault(parent_id, []).append(mintmark.id)

    ordered: list[int] = []
    visited: set[int] = set()

    def visit(mintmark_id: int) -> None:
        if mintmark_id in visited:
            return
        visited.add(mintmark_id)
        ordered.append(mintmark_id)
        for child_id in sorted(children_by_parent.get(mintmark_id, ())):
            visit(child_id)

    for root_id in sorted(root_ids):
        visit(root_id)
    for mintmark_id in sorted(mintmarks):
        visit(mintmark_id)
    return tuple(ordered)


def _format_attribute(label: str, value: float, col_width: int = 8) -> str:
    text = f"-{label}{value}"
    cjk_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return text + "\u2007" * max(col_width - len(text) - cjk_count, 1)


def _format_pet(pet: PetORM) -> str:
    return f"{pet.name}（{pet.id}）"


def _gem_reply(category: GemCategoryORM) -> QueryReply:
    lines = [
        f"【Lv.{gem.level}】 "
        + " | ".join(effect.info for effect in gem.skill_effect_in_use)
        for gem in category.gem
    ]
    return QueryReply(
        text=f"💎以下是{category.name}系列信息：\n" + "\n".join(lines)
    )
