# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepare immutable new-content menu data before any asset I/O begins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.integrations.seer_data.skin_image_resolution import (
    load_skin_image_resolutions,
)
from ironsbot.services.seer.autocard import AutocardPromptValue

from .new_content_details import (
    NewContentItemDetails,
    load_new_content_peak_pool_details,
    load_new_content_skill_details,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.autocard import AutocardEntry, AutocardService
    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.new_content import (
        NewContentCategory,
        NewContentItem,
        NewContentSnapshot,
    )


_EQUIP_PART_TYPE_NAMES = {
    0: "头部",
    1: "眼部",
    2: "腰部",
    3: "手部",
    4: "脚部",
    5: "背景",
    6: "星际座驾",
}


@dataclass(frozen=True, slots=True)
class NewContentAssetRequest:
    """A stable image request with no image-source or ORM dependency."""

    kind: str | None = None
    key: str | None = None
    url: str | None = None
    required: bool = False
    layout: str = "square"
    fallback_data: bytes | None = None


@dataclass(frozen=True, slots=True)
class NewContentPreparedItem:
    """One fully resolved content row before image bytes are fetched."""

    item: NewContentItem
    details: NewContentItemDetails
    asset: NewContentAssetRequest | None


class NewContentSnapshotBuilder:
    """Read release facts and create immutable menu rows in one sync phase."""

    def __init__(self, data: SeerDataAccess, autocard: AutocardService) -> None:
        self._data = data
        self._autocard = autocard

    def prepare(
        self,
        snapshot: NewContentSnapshot,
        category: NewContentCategory | None,
    ) -> tuple[NewContentPreparedItem, ...]:
        if category is None:
            return ()
        return tuple(self.prepare_item(item) for item in snapshot.items_for(category))

    def prepare_item(self, item: NewContentItem) -> NewContentPreparedItem:
        """Resolve every database and service value before the renderer awaits."""

        autocard_entry = self._autocard_entry(item)
        details = self._item_details(item, autocard_entry)
        return NewContentPreparedItem(
            item=item,
            details=details,
            asset=self._asset_request(item, autocard_entry),
        )

    def _item_details(
        self,
        item: NewContentItem,
        autocard_entry: AutocardEntry | None,
    ) -> NewContentItemDetails:
        resolvers = {
            "pet": lambda: self._pet_details(item),
            "peak_pool": lambda: load_new_content_peak_pool_details(self._data, item),
            "pet_skin": lambda: self._skin_details(item),
            "skill": lambda: load_new_content_skill_details(self._data, item),
            "mintmark": lambda: self._mintmark_details(item),
            "suit": lambda: self._suit_details(item),
            "equip": lambda: self._equip_details(item),
            "mount": lambda: self._equip_details(item),
            "achievement": lambda: self._achievement_details(item),
            "autocard_card": lambda: _autocard_details(item, autocard_entry),
            "autocard_role": lambda: _autocard_details(item, autocard_entry),
        }
        try:
            resolver = resolvers.get(item.category)
            if resolver is not None:
                return resolver()
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
            # A content release can briefly arrive before every referenced table.
            # Its index wording remains useful while the source catches up.
            pass
        return _fallback_details(item)

    def _pet_details(self, item: NewContentItem) -> NewContentItemDetails:
        with self._data.get(self._data.pet, item.entity_id) as pet:
            if pet is None:
                return _fallback_details(item)
            attributes = pet.base_stats.to_model().round()
            return NewContentItemDetails(
                metadata=f"ID: {pet.id}",
                description=(
                    pet.encyclopedia.introduction.strip()
                    if pet.encyclopedia is not None
                    else "暂无官方简介"
                ),
                stats=_two_column_stats(attributes),
                stats_layout="two_column",
                stats_total=_stats_total(attributes),
                type_id=int(pet.type.id),
                gender_id=int(pet.gender.id),
                type_name=str(pet.type.name),
                gender_name=_gender_name(str(pet.gender.name)),
            )

    def _skin_details(self, item: NewContentItem) -> NewContentItemDetails:
        with self._data.get(self._data.pet_skin, item.entity_id) as skin:
            if skin is None:
                return _fallback_details(item)
            pet = skin.pet
            return NewContentItemDetails(
                metadata=(
                    f"ID：{skin.id}｜绑定精灵：{pet.name}"
                    if pet is not None
                    else f"ID：{skin.id}"
                ),
                description=str(getattr(skin, "description", "") or "暂无官方简介"),
                type_id=None if pet is None else int(pet.type.id),
                gender_id=None if pet is None else int(pet.gender.id),
                type_name="" if pet is None else str(pet.type.name),
                gender_name=("" if pet is None else _gender_name(str(pet.gender.name))),
            )

    def _mintmark_details(self, item: NewContentItem) -> NewContentItemDetails:
        with self._data.get(self._data.mintmark, item.entity_id) as mintmark:
            if mintmark is None:
                return _fallback_details(item)
            attributes = _mintmark_attributes(mintmark)
            return NewContentItemDetails(
                metadata=f"ID：{mintmark.id}",
                description="",
                stats=() if attributes is None else _two_column_stats(attributes),
                stats_layout="two_column",
                stats_total="" if attributes is None else _stats_total(attributes),
            )

    def _suit_details(self, item: NewContentItem) -> NewContentItemDetails:
        with self._data.get(self._data.suit, item.entity_id) as suit:
            if suit is None:
                return _fallback_details(item)
            return NewContentItemDetails(
                metadata=f"ID：{suit.id}",
                description=str(suit.suit_desc or "暂无官方简介").strip(),
                side_title="套装效果",
                side_description=(
                    str(suit.bonus.desc).strip()
                    if getattr(suit, "bonus", None) is not None
                    and getattr(suit.bonus, "desc", "")
                    else "暂无套装效果"
                ),
            )

    def _equip_details(self, item: NewContentItem) -> NewContentItemDetails:
        with self._data.get(self._data.equip, item.entity_id) as equip:
            if equip is None:
                return _fallback_details(item)
            part_name = _EQUIP_PART_TYPE_NAMES.get(
                int(getattr(equip.part_type, "id", -1)),
                str(equip.part_type.name),
            )
            suit_name = str(equip.suit.name) if equip.suit is not None else "无"
            description = (
                str(equip.bonus.desc).strip()
                if equip.bonus is not None and equip.bonus.desc
                else "暂无官方简介"
            )
            return NewContentItemDetails(
                metadata=f"ID：{equip.id}｜类型：{part_name}｜套装：{suit_name}",
                description=description,
            )

    def _achievement_details(self, item: NewContentItem) -> NewContentItemDetails:
        title_id, title_name = _first_title(item)
        bonus = "暂无称号加成"
        if title_id:
            with self._data.get(self._data.title, title_id) as title:
                if title is not None and title.ability_desc:
                    bonus = str(title.ability_desc).strip()
        point = int(item.payload.get("point", 0))
        suffix = f"｜称号：{title_name}" if title_name else ""
        return NewContentItemDetails(
            metadata=f"成就 ID：{item.entity_id}｜{point} 点{suffix}",
            description="",
            side_title="称号加成",
            side_description=bonus,
        )

    def _autocard_entry(self, item: NewContentItem) -> AutocardEntry | None:
        kind = {
            "autocard_card": "card",
            "autocard_role": "role",
        }.get(item.category)
        if kind is None and item.category == "autocard_sanctuary_effect":
            relation_kind, resource_id = _sanctuary_relation(item.payload)
            kind = "card" if relation_kind == "card" else None
            if kind is not None:
                return self._autocard.select(
                    AutocardPromptValue(kind=kind, item_id=resource_id)
                )
        if kind is None:
            return None
        return self._autocard.select(
            AutocardPromptValue(kind=kind, item_id=item.entity_id)
        )

    def _asset_request(  # noqa: PLR0911
        self,
        item: NewContentItem,
        autocard_entry: AutocardEntry | None,
    ) -> NewContentAssetRequest | None:
        if item.category == "skill":
            return None
        if item.category in {"pet", "peak_pool"}:
            resource_id = int(item.payload.get("resource_id", item.entity_id))
            return _seer_asset("pet_head", resource_id, required=True)
        if item.category == "pet_skin":
            return _seer_asset(
                "pet_head",
                self._skin_head_resource_id(item),
                required=True,
            )
        image_kinds = {
            "mintmark": "mintmark",
            "suit": "suit",
            "equip": "equip",
            "mount": "equip",
        }
        if kind := image_kinds.get(item.category):
            return _seer_asset(kind, item.entity_id, required=True)
        if item.category == "achievement":
            title_id, _title_name = _first_title(item)
            return _seer_asset("title", title_id, required=bool(title_id))
        if item.category in {"autocard_card", "autocard_role"}:
            return _autocard_asset(autocard_entry, required=True, layout="portrait")
        if item.category == "autocard_sanctuary_effect":
            relation_kind, resource_id = _sanctuary_relation(item.payload)
            if relation_kind == "pet":
                return _seer_asset("pet_head", resource_id)
            if relation_kind == "card":
                return _autocard_asset(autocard_entry, layout="portrait")
        return None

    def _skin_head_resource_id(self, item: NewContentItem) -> int:
        with self._data.query(
            lambda session: load_skin_image_resolutions(session, (item.entity_id,))
        ) as resolutions:
            resolution = resolutions.get(item.entity_id)
        return (
            resolution.head_resource_id
            if resolution is not None and resolution.head_resource_id > 0
            else int(item.payload.get("resource_id", item.entity_id))
        )


def _seer_asset(
    kind: str,
    resource_id: int,
    *,
    required: bool = False,
    fallback_data: bytes | None = None,
) -> NewContentAssetRequest:
    return NewContentAssetRequest(
        kind=kind,
        key=str(resource_id),
        required=required and resource_id > 0,
        fallback_data=fallback_data,
    )


def _autocard_asset(
    entry: AutocardEntry | None,
    *,
    required: bool = False,
    layout: str = "square",
) -> NewContentAssetRequest | None:
    if entry is None or not entry.image_url:
        return None
    return NewContentAssetRequest(
        url=entry.image_url,
        required=required,
        layout=layout,
    )


def _autocard_details(
    item: NewContentItem,
    entry: AutocardEntry | None,
) -> NewContentItemDetails:
    if entry is None:
        return _fallback_details(item)
    skill_lines = [entry.skill_text]
    if entry.skill_upgrade:
        skill_lines.append(f"升级：{entry.skill_upgrade}")
    side_description = "\n".join(line for line in skill_lines if line)
    return NewContentItemDetails(
        metadata=f"ID：{entry.item_id}｜{'角色' if entry.kind == 'role' else '卡牌'}",
        description=entry.description,
        side_title=(
            f"技能：{entry.skill_name}"
            if entry.skill_name
            else ("技能效果" if side_description else "")
        ),
        side_description=side_description,
    )


def _fallback_details(item: NewContentItem) -> NewContentItemDetails:
    change = "修改" if item.change_kind == "modified" else "新增"
    if item.category == "autocard_sanctuary_effect":
        sanctuary = str(item.payload.get("sanctuary_name", "")).strip()
        phase = int(item.payload.get("unlock_round", 0))
        return NewContentItemDetails(
            metadata=f"ID：{item.entity_id}",
            description=(
                f"圣域：{sanctuary or '未命名'}｜"
                f"{'基础圣域' if phase == 0 else f'第 {phase} 回合祝印'}"
            ),
            side_title="圣域效果",
            side_description=str(item.payload.get("description", "") or "暂无官方说明"),
        )
    return NewContentItemDetails(
        metadata=f"{change}｜ID：{item.entity_id}",
        description="暂无官方简介",
    )


def _two_column_stats(attributes: object) -> tuple[tuple[str, str], ...]:
    return tuple(
        (label, str(getattr(attributes, key, 0)))
        for label, key in (
            ("攻击", "atk"),
            ("防御", "def_"),
            ("特攻", "sp_atk"),
            ("特防", "sp_def"),
            ("速度", "spd"),
            ("体力", "hp"),
        )
    )


def _stats_total(attributes: object) -> str:
    total = float(getattr(attributes, "total", 0))
    return str(int(total)) if total.is_integer() else f"{total:g}"


def _mintmark_attributes(mintmark: object) -> object | None:
    part = (
        getattr(mintmark, "ability_part", None)
        or getattr(mintmark, "skill_part", None)
        or getattr(mintmark, "universal_part", None)
    )
    if part is None or getattr(mintmark, "skill_part", None) is part:
        return None
    max_value = getattr(part, "max_attr_value", None)
    if max_value is None:
        return None
    attributes = max_value.to_model()
    extra_value = getattr(part, "extra_attr_value", None)
    if extra_value is not None:
        attributes = attributes + extra_value.to_model()
    return attributes.round()


def _gender_name(value: str) -> str:
    return {"male": "雄性", "female": "雌性", "none": "无性别"}.get(
        value.casefold(),
        value,
    )


def _first_title(item: NewContentItem) -> tuple[int, str]:
    titles = item.payload.get("titles", [])
    first_title = titles[0] if isinstance(titles, list) and titles else {}
    if not isinstance(first_title, dict):
        return 0, ""
    try:
        return (
            int(first_title.get("id", first_title.get("title_id", 0))),
            str(first_title.get("name", "")),
        )
    except (TypeError, ValueError):
        return 0, ""


def _sanctuary_relation(payload: dict[str, object]) -> tuple[str, int]:
    relation_type = str(
        payload.get("target_type")
        or payload.get("source_type")
        or payload.get("entity_type")
        or ""
    ).casefold()
    card_id = _payload_id(payload, "sanctuary_card_id", "autocard_card_id", "card_id")
    pet_id = _payload_id(payload, "sanctuary_pet_id", "pet_id", "monster_id")
    target_id = _payload_id(payload, "target_id", "source_id", "entity_id")
    if relation_type in {"card", "autocard_card"}:
        card_id = card_id or target_id
    elif relation_type in {"pet", "monster", "seer_pet"}:
        pet_id = pet_id or target_id
    if card_id:
        return "card", card_id
    if pet_id:
        return "pet", pet_id
    return "", 0


def _payload_id(payload: dict[str, object], *keys: str) -> int:
    for key in keys:
        raw_value = payload.get(key, 0)
        if not isinstance(raw_value, int | str | float):
            continue
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0
