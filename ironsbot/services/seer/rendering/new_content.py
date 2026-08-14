# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the release-level new-content menu as a game-style image."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, TypedDict

from ironsbot.services.seer.autocard import (
    AutocardEntry,
    AutocardPromptValue,
    AutocardService,
)
from ironsbot.services.seer.flash_mount_images import load_flash_mount_image
from ironsbot.services.seer.images import ImageSourceError, SeerImageSource, to_data_uri
from ironsbot.services.seer.new_content import (
    CATEGORY_NAMES,
    PEAK_POOL_NEW_CONTENT_CATEGORIES,
    NewContentCategory,
    NewContentItem,
    NewContentSnapshot,
    format_new_content_category_count,
    new_content_category_preview_items,
)
from ironsbot.services.seer.render_paths import (
    NEW_CONTENT_TEMPLATE_PATH,
    PET_INFO_IMAGES_PATH,
    SHARED_TEMPLATE_PATH,
)
from ironsbot.services.seer.skin_image_resolution import load_skin_image_resolutions

from .new_content_pool_changes import (
    PoolChangePreviewDict,
    load_pool_change_images,
    pool_change_preview,
)
from .new_content_render_policy import (
    item_requires_image as _item_requires_image,
)
from .new_content_render_policy import new_content_cache_key as _cache_key
from .new_content_skill_details import (
    SKILL_CATEGORY_ATTRIBUTE as _SKILL_CATEGORY_ATTRIBUTE,
)
from .new_content_skill_details import (
    NewContentItemDetails as _ItemDetails,
)
from .new_content_skill_details import (
    load_new_content_skill_details as _skill_details,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.new_content import NewContentItem
    from ironsbot.services.seer.render_cache import RenderCache

    from . import HtmlTemplateRenderer
    from .custom_pet_models import SkillDict


class NewContentMenuItemDict(TypedDict):
    code: str
    name: str
    description: str
    metadata: str
    side_title: str
    side_description: str
    stats: tuple[tuple[str, str], ...]
    stats_layout: str
    stats_total: str
    type_name: str
    gender_name: str
    type_icon: str | None
    gender_icon: str | None
    image_layout: str
    is_category: bool
    expanded: bool
    image: str | None
    image_notice: str
    skill: SkillDict | None
    friend_skill: SkillDict | None
    pool_preview: PoolChangePreviewDict | None


_EQUIP_PART_TYPE_NAMES = {
    0: "头部",
    1: "眼部",
    2: "腰部",
    3: "手部",
    4: "脚部",
    5: "背景",
    6: "星际座驾",
}
MOUNT_IMAGE_PENDING_NOTICE = "官方图片暂未上线"


async def render_new_content_menu(  # noqa: PLR0913
    cache: RenderCache,
    data: SeerDataAccess,
    images: SeerImageSource,
    autocard: AutocardService,
    render_html: HtmlTemplateRenderer,
    snapshot: NewContentSnapshot,
    display_categories: tuple[NewContentCategory, ...],
    focused_category: NewContentCategory | None,
    menu_title: str = "新增内容",
    expanded_categories: frozenset[NewContentCategory] = frozenset(),
    auto_expand_max_items: int = 5,
) -> bytes:
    """Render the active categories and items without requiring every asset."""
    content_key = _cache_key(
        snapshot,
        display_categories,
        focused_category,
        menu_title,
        expanded_categories,
        auto_expand_max_items,
    )
    if cached := cache.get("new_content", content_key):
        return cached

    pool_items = (
        tuple(
            item
            for item in snapshot.items
            if item.category in PEAK_POOL_NEW_CONTENT_CATEGORIES
            and item.category in display_categories
        )
        if focused_category is None
        else ()
    )
    pool_images = await load_pool_change_images(images, pool_items)
    cacheable = all(image is not None for image in pool_images.values())

    rows: list[NewContentMenuItemDict] = []
    item_rows: list[tuple[int, NewContentItem, _ItemDetails]] = []
    if focused_category is not None:
        for index, item in enumerate(snapshot.items_for(focused_category), start=1):
            details = _item_details(data, autocard, item)
            rows.append(
                {
                    "code": str(index),
                    "name": item.name,
                    "description": details.description,
                    "metadata": details.metadata,
                    "side_title": details.side_title,
                    "side_description": details.side_description,
                    "stats": details.stats,
                    "stats_layout": details.stats_layout,
                    "stats_total": details.stats_total,
                    "type_name": details.type_name,
                    "gender_name": details.gender_name,
                    "type_icon": None,
                    "gender_icon": _gender_icon_data_uri(details.gender_id),
                    "image_layout": _item_image_layout(item),
                    "is_category": False,
                    "expanded": False,
                    "image": None,
                    "image_notice": "",
                    "skill": details.skill,
                    "friend_skill": details.friend_skill,
                    "pool_preview": None,
                }
            )
            item_rows.append((len(rows) - 1, item, details))
    else:
        for index, category in enumerate(display_categories):
            code = chr(ord("a") + index)
            items = snapshot.items_for(category)
            pool_preview = (
                pool_change_preview(category, items, pool_images)
                if category in PEAK_POOL_NEW_CONTENT_CATEGORIES
                else None
            )
            expanded = (
                category in expanded_categories
                and category not in PEAK_POOL_NEW_CONTENT_CATEGORIES
                and auto_expand_max_items > 0
            )
            preview_items = (
                new_content_category_preview_items(
                    snapshot,
                    category,
                    auto_expand_max_items,
                )
                if expanded
                else ()
            )
            rows.append(
                {
                    "code": code,
                    "name": CATEGORY_NAMES[category],
                    "description": (
                        f"{len(items)} 只变化"
                        if category in PEAK_POOL_NEW_CONTENT_CATEGORIES
                        else format_new_content_category_count(items)
                    ),
                    "metadata": "",
                    "side_title": "",
                    "side_description": "",
                    "stats": (),
                    "stats_layout": "inline",
                    "stats_total": "",
                    "type_name": "",
                    "gender_name": "",
                    "type_icon": None,
                    "gender_icon": None,
                    "image_layout": "square",
                    "is_category": True,
                    "expanded": expanded,
                    "image": None,
                    "image_notice": "",
                    "skill": None,
                    "friend_skill": None,
                    "pool_preview": pool_preview,
                }
            )
            if expanded:
                for item_index, item in enumerate(preview_items, start=1):
                    details = _item_details(data, autocard, item)
                    rows.append(
                        {
                            "code": f"{code}{item_index}",
                            "name": item.name,
                            "description": details.description,
                            "metadata": details.metadata,
                            "side_title": details.side_title,
                            "side_description": details.side_description,
                            "stats": details.stats,
                            "stats_layout": details.stats_layout,
                            "stats_total": details.stats_total,
                            "type_name": details.type_name,
                            "gender_name": details.gender_name,
                            "type_icon": None,
                            "gender_icon": _gender_icon_data_uri(details.gender_id),
                            "image_layout": _item_image_layout(item),
                            "is_category": False,
                            "expanded": False,
                            "image": None,
                            "image_notice": "",
                            "skill": details.skill,
                            "friend_skill": details.friend_skill,
                            "pool_preview": None,
                        }
                    )
                    item_rows.append((len(rows) - 1, item, details))

    image_results = await asyncio.gather(
        *(
            _item_visuals(data, images, autocard, item, details)
            for _row_index, item, details in item_rows
        )
    )
    for (row_index, item, _details), (image, type_icon, image_notice) in zip(
        item_rows,
        image_results,
        strict=True,
    ):
        rows[row_index]["image"] = image
        rows[row_index]["type_icon"] = type_icon
        rows[row_index]["image_notice"] = image_notice
        if _item_requires_image(item) and image is None:
            cacheable = False

    skill_type_icons = await _load_skill_type_icons(
        images,
        item_rows,
        image_results,
    )

    result = await render_html(
        template_path=[NEW_CONTENT_TEMPLATE_PATH, SHARED_TEMPLATE_PATH],
        template_name="template.html.j2",
        templates={
            "content_date": snapshot.weekly_cycle,
            "menu_title": menu_title,
            "items": rows,
            "skill_type_icons": skill_type_icons,
            "focused_category": focused_category,
        },
        max_width=1080,
        allow_refit=False,
    )
    if cacheable:
        cache.put("new_content", content_key, result)
    return result


async def _load_skill_type_icons(
    images: SeerImageSource,
    item_rows: list[tuple[int, NewContentItem, _ItemDetails]],
    image_results: list[tuple[str | None, str | None, str]],
) -> dict[int | str, str]:
    """Build the icon map expected by the shared pet skill-card macro."""

    type_icons: dict[int | str, str] = {"prop": ""}
    has_attribute_skill = False
    for (_row_index, _item, details), (_image, type_icon, _image_notice) in zip(
        item_rows,
        image_results,
        strict=True,
    ):
        if details.skill is None:
            continue
        type_icons[details.skill["type_id"]] = type_icon or ""
        has_attribute_skill |= (
            details.skill["category_id"] == _SKILL_CATEGORY_ATTRIBUTE
        )
    if has_attribute_skill:
        type_icons["prop"] = await _type_icon(images, "prop") or ""
    return type_icons


async def _item_visuals(
    data: SeerDataAccess,
    images: SeerImageSource,
    autocard: AutocardService,
    item: NewContentItem,
    details: _ItemDetails,
) -> tuple[str | None, str | None, str]:
    image, type_icon = await asyncio.gather(
        _item_image(data, images, autocard, item),
        _type_icon(images, details.type_id),
    )
    image_notice = (
        MOUNT_IMAGE_PENDING_NOTICE
        if item.category == "mount" and image is None
        else ""
    )
    return image, type_icon, image_notice


async def _type_icon(
    images: SeerImageSource,
    type_id: int | str | None,
) -> str | None:
    if type_id is None:
        return None
    try:
        if isinstance(type_id, str):
            return to_data_uri(
                await images.fetch("element_type", type_id, fallback=False)  # type: ignore[arg-type]
            )
        return await _fetch_data_uri(images, "element_type", type_id)
    except ImageSourceError:
        return None


def _item_details(
    data: SeerDataAccess,
    autocard: AutocardService,
    item: NewContentItem,
) -> _ItemDetails:
    """Read the small amount of extra data worth putting on one menu row."""

    resolvers = {
        "pet": lambda: _pet_details(data, item),
        "pet_skin": lambda: _skin_details(data, item),
        "skill": lambda: _skill_details(data, item),
        "mintmark": lambda: _mintmark_details(data, item),
        "suit": lambda: _suit_details(data, item),
        "equip": lambda: _equip_details(data, item),
        "mount": lambda: _equip_details(data, item),
        "achievement": lambda: _achievement_details(data, item),
        "autocard_card": lambda: _autocard_details(autocard, item),
        "autocard_role": lambda: _autocard_details(autocard, item),
    }
    try:
        resolver = resolvers.get(item.category)
        if resolver is not None:
            return resolver()
    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
        # A new-content index can briefly get ahead of a data table. The menu
        # still remains useful with its release-index wording in that case.
        pass
    return _fallback_details(item)


def _pet_details(data: SeerDataAccess, item: NewContentItem) -> _ItemDetails:
    with data.get(data.pet, item.entity_id) as pet:
        if pet is None:
            return _fallback_details(item)
        attributes = pet.base_stats.to_model().round()
        return _ItemDetails(
            metadata=f"ID: {pet.id}",
            description=pet.encyclopedia.introduction.strip()
            if pet.encyclopedia is not None
            else "暂无官方简介",
            stats=_two_column_stats(attributes),
            stats_layout="two_column",
            stats_total=_stats_total(attributes),
            type_id=int(pet.type.id),
            gender_id=int(pet.gender.id),
            type_name=str(pet.type.name),
            gender_name=_gender_name(str(pet.gender.name)),
        )


def _skin_details(data: SeerDataAccess, item: NewContentItem) -> _ItemDetails:
    with data.get(data.pet_skin, item.entity_id) as skin:
        if skin is None:
            return _fallback_details(item)
        pet = skin.pet
        return _ItemDetails(
            metadata=(
                f"ID：{skin.id}｜绑定精灵：{pet.name}"
                if pet is not None
                else f"ID：{skin.id}"
            ),
            description=str(getattr(skin, "description", "") or "暂无官方简介"),
            type_id=None if pet is None else int(pet.type.id),
            gender_id=None if pet is None else int(pet.gender.id),
            type_name="" if pet is None else str(pet.type.name),
            gender_name=(
                "" if pet is None else _gender_name(str(pet.gender.name))
            ),
        )


def _mintmark_details(data: SeerDataAccess, item: NewContentItem) -> _ItemDetails:
    with data.get(data.mintmark, item.entity_id) as mintmark:
        if mintmark is None:
            return _fallback_details(item)
        attributes = _mintmark_attributes(mintmark)
        return _ItemDetails(
            metadata=f"ID：{mintmark.id}",
            # The six stat cells are the useful compact summary here. The
            # raw part description repeats those values and makes the row
            # needlessly tall; full details remain available via the item.
            description="",
            stats=() if attributes is None else _two_column_stats(attributes),
            stats_layout="two_column",
            stats_total="" if attributes is None else _stats_total(attributes),
        )


def _suit_details(data: SeerDataAccess, item: NewContentItem) -> _ItemDetails:
    with data.get(data.suit, item.entity_id) as suit:
        if suit is None:
            return _fallback_details(item)
        return _ItemDetails(
            metadata=f"ID：{suit.id}",
            description=str(suit.suit_desc or "暂无官方介绍").strip(),
            side_title="套装效果",
            side_description=str(
                suit.bonus.desc if suit.bonus is not None else "暂无套装效果"
            ).strip(),
        )


def _equip_details(data: SeerDataAccess, item: NewContentItem) -> _ItemDetails:
    with data.get(data.equip, item.entity_id) as equip:
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
        return _ItemDetails(
            metadata=f"ID：{equip.id}｜类型：{part_name}｜套装：{suit_name}",
            description=description,
        )


def _achievement_details(data: SeerDataAccess, item: NewContentItem) -> _ItemDetails:
    titles = item.payload.get("titles", [])
    first_title = titles[0] if isinstance(titles, list) and titles else {}
    title_id = 0
    title_name = ""
    if isinstance(first_title, dict):
        title_id = int(first_title.get("id", first_title.get("title_id", 0)))
        title_name = str(first_title.get("name", ""))
    bonus = "暂无称号加成"
    if title_id:
        with data.get(data.title, title_id) as title:
            if title is not None and title.ability_desc:
                bonus = str(title.ability_desc).strip()
    point = int(item.payload.get("point", 0))
    suffix = f"｜称号：{title_name}" if title_name else ""
    return _ItemDetails(
        metadata=f"成就 ID：{item.entity_id}｜{point} 点{suffix}",
        description="",
        side_title="称号加成",
        side_description=bonus,
    )


def _autocard_details(
    autocard: AutocardService,
    item: NewContentItem,
) -> _ItemDetails:
    entry = autocard.select(
        AutocardPromptValue(
            kind="role" if item.category == "autocard_role" else "card",
            item_id=item.entity_id,
        )
    )
    if entry is None:
        return _fallback_details(item)
    skill_lines = [entry.skill_text]
    if entry.skill_upgrade:
        skill_lines.append(f"升级：{entry.skill_upgrade}")
    side_description = "\n".join(line for line in skill_lines if line)
    return _ItemDetails(
        metadata=f"ID：{entry.item_id}｜{'角色' if entry.kind == 'role' else '卡牌'}",
        description=entry.description,
        side_title=(
            f"技能：{entry.skill_name}"
            if entry.skill_name
            else ("技能效果" if side_description else "")
        ),
        side_description=side_description,
    )


def _fallback_details(item: NewContentItem) -> _ItemDetails:
    change = "修改" if item.change_kind == "modified" else "新增"
    if item.category == "autocard_sanctuary_effect":
        sanctuary = str(item.payload.get("sanctuary_name", "")).strip()
        phase = int(item.payload.get("unlock_round", 0))
        return _ItemDetails(
            metadata=f"ID：{item.entity_id}",
            description=(
                f"圣域：{sanctuary or '未命名'}｜"
                f"{'基础圣域' if phase == 0 else f'第 {phase} 回合祝印'}"
            ),
            side_title="圣域效果",
            side_description=str(
                item.payload.get("description", "") or "暂无官方说明"
            ),
        )
    return _ItemDetails(
        metadata=f"{change}｜ID：{item.entity_id}",
        description="暂无官方简介",
    )


def _six_stats(attributes: object) -> tuple[tuple[str, str], ...]:
    return tuple(
        (label, str(getattr(attributes, key, 0)))
        for label, key in (
            ("攻击", "atk"),
            ("特攻", "sp_atk"),
            ("速度", "spd"),
            ("防御", "def_"),
            ("特防", "sp_def"),
            ("体力", "hp"),
        )
    )


def _two_column_stats(attributes: object) -> tuple[tuple[str, str], ...]:
    """Pair physical/special stats into the right-side 3x2 mintmark table."""

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


def _gender_icon_data_uri(gender_id: int | None) -> str | None:
    if gender_id is None:
        return None
    icon_path = PET_INFO_IMAGES_PATH / f"{gender_id}.png"
    if not icon_path.exists():
        icon_path = PET_INFO_IMAGES_PATH / "0.png"
    return to_data_uri(icon_path.read_bytes())


def _gender_name(value: str) -> str:
    return {
        "male": "雄性",
        "female": "雌性",
        "none": "无性别",
    }.get(value.casefold(), value)


async def _item_image(
    data: SeerDataAccess,
    images: SeerImageSource,
    autocard: AutocardService,
    item: NewContentItem,
) -> str | None:
    try:
        image: str | None = None
        if item.category == "skill":
            image = None
        elif item.category == "autocard_sanctuary_effect":
            image = await _sanctuary_item_image(images, autocard, item)
        elif item.category == "achievement":
            image = await _achievement_title_image(images, item)
        elif item.category in {"autocard_card", "autocard_role"}:
            image = await _autocard_item_image(images, autocard, item)
        elif item.category == "mount":
            image = await _mount_item_image(data, images, item)
        elif image_request := _item_image_request(data, item):
            kind, resource_id = image_request
            image = await _fetch_data_uri(images, kind, resource_id)
    except (ImageSourceError, RuntimeError, ValueError, TypeError):
        return None
    else:
        return image


async def _mount_item_image(
    data: SeerDataAccess,
    images: SeerImageSource,
    item: NewContentItem,
) -> str | None:
    try:
        return await _fetch_data_uri(images, "equip", item.entity_id)
    except ImageSourceError:
        fallback = load_flash_mount_image(data, item.entity_id)
        return None if fallback is None else to_data_uri(fallback)


def _item_image_request(
    data: SeerDataAccess,
    item: NewContentItem,
) -> tuple[str, int] | None:
    if item.category == "pet":
        return "pet_head", int(item.payload.get("resource_id", item.entity_id))
    if item.category == "pet_skin":
        return "pet_head", _skin_head_resource_id(data, item)
    image_kinds = {
        "mintmark": "mintmark",
        "suit": "suit",
        "equip": "equip",
        "mount": "equip",
    }
    kind = image_kinds.get(item.category)
    return None if kind is None else (kind, item.entity_id)


async def _autocard_item_image(
    images: SeerImageSource,
    autocard: AutocardService,
    item: NewContentItem,
) -> str | None:
    entry = autocard.select(
        AutocardPromptValue(
            kind="role" if item.category == "autocard_role" else "card",
            item_id=item.entity_id,
        )
    )
    return await _autocard_entry_image(images, entry)


async def _sanctuary_item_image(
    images: SeerImageSource,
    autocard: AutocardService,
    item: NewContentItem,
) -> str | None:
    """Use the explicit sanctuary relation instead of guessing from its name."""

    relation_kind, resource_id = _sanctuary_relation(item.payload)
    if relation_kind == "card":
        entry = autocard.select(
            AutocardPromptValue(kind="card", item_id=resource_id)
        )
        return await _autocard_entry_image(images, entry)
    if relation_kind == "pet":
        return await _fetch_data_uri(images, "pet_head", resource_id)
    return None


def _sanctuary_relation(payload: dict[str, object]) -> tuple[str, int]:
    """Return the explicit target kind and ID carried by a sanctuary record."""

    relation_type = str(
        payload.get("target_type")
        or payload.get("source_type")
        or payload.get("entity_type")
        or ""
    ).casefold()
    card_id = _payload_id(
        payload,
        "sanctuary_card_id",
        "autocard_card_id",
        "card_id",
    )
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


def _item_image_layout(item: NewContentItem) -> str:
    if item.category in {"autocard_card", "autocard_role"}:
        return "portrait"
    if item.category == "autocard_sanctuary_effect":
        relation_kind, _resource_id = _sanctuary_relation(item.payload)
        return "portrait" if relation_kind == "card" else "square"
    return "square"


async def _autocard_entry_image(
    images: SeerImageSource,
    entry: AutocardEntry | None,
) -> str | None:
    if entry is None or not entry.image_url:
        return None
    return to_data_uri(await images.fetch_url(entry.image_url))


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


def _skin_head_resource_id(data: SeerDataAccess, item: NewContentItem) -> int:
    with data.query(
        lambda session: load_skin_image_resolutions(session, (item.entity_id,))
    ) as resolutions:
        resolution = resolutions.get(item.entity_id)
    return (
        resolution.head_resource_id
        if resolution is not None and resolution.head_resource_id > 0
        else int(item.payload.get("resource_id", item.entity_id))
    )


async def _achievement_title_image(
    images: SeerImageSource,
    item: NewContentItem,
) -> str | None:
    titles = item.payload.get("titles", [])
    if not isinstance(titles, list) or not titles or not isinstance(titles[0], dict):
        return None
    title_id = titles[0].get("id", titles[0].get("title_id", 0))
    return await _fetch_data_uri(images, "title", int(title_id)) if title_id else None


async def _fetch_data_uri(
    images: SeerImageSource,
    kind: str,
    key: int,
) -> str | None:
    if key <= 0:
        return None
    data = await images.fetch(kind, str(key), fallback=False)  # type: ignore[arg-type]
    return to_data_uri(data)
