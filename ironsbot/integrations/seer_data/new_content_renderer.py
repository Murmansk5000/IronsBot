# SPDX-License-Identifier: GPL-3.0-or-later
"""Materialize and render a prepared release-level new-content menu."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from ironsbot.integrations.seer_data.flash_mount_repository import (
    load_flash_mount_image,
)
from ironsbot.services.seer.images import (
    ImageSourceError,
    SeerImageSource,
    to_data_uri,
)
from ironsbot.services.seer.new_content import (
    CATEGORY_NAMES,
    NewContentCategory,
    NewContentSnapshot,
    format_new_content_category_count,
    is_new_content_category_auto_expanded,
)
from ironsbot.services.seer.render_paths import PET_INFO_IMAGES_PATH
from ironsbot.services.seer.rendering.cache_key import render_request_cache_key
from ironsbot.services.seer.rendering.new_content import (
    NewContentMenuItem,
    present_new_content_menu,
    render_new_content_document,
)

from .new_content_details import SKILL_CATEGORY_ATTRIBUTE
from .new_content_snapshot import (
    NewContentAssetRequest,
    NewContentPreparedItem,
    NewContentSnapshotBuilder,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.autocard import AutocardService
    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer


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
    """Render a release menu after all database state is frozen in a snapshot."""

    request_key = _cache_key(
        snapshot,
        display_categories,
        focused_category,
        menu_title,
        expanded_categories,
        auto_expand_max_items,
    )
    if cached := cache.get("new_content", request_key):
        return cached

    # All ORM and domain-service reads complete before the first await below.
    expanded: frozenset[NewContentCategory] = frozenset(
        category
        for category in display_categories
        if category in expanded_categories
        or (
            focused_category is None
            and is_new_content_category_auto_expanded(
                snapshot,
                category,
                auto_expand_max_items,
            )
        )
    )
    builder = NewContentSnapshotBuilder(data, autocard)
    prepared_items = tuple(
        prepared
        for category in display_categories
        if focused_category is not None or category in expanded
        for prepared in builder.prepare(snapshot, category)
    )
    prepared_items = tuple(
        _with_mount_fallback(data, prepared) for prepared in prepared_items
    )
    rows = _initial_rows(
        snapshot,
        display_categories,
        prepared_items,
        focused_category,
        expanded,
    )
    visuals = await asyncio.gather(
        *(_item_visuals(images, prepared) for prepared in prepared_items)
    )

    # Arbitrary card URLs are not published by the immutable Seer asset
    # manifest, so a final image containing one must not outlive its source.
    cacheable = all(
        prepared.asset is None or prepared.asset.url is None
        for prepared in prepared_items
    )
    prepared_by_key = {
        (prepared.item.category, prepared.item.entity_id): (prepared, visual)
        for prepared, visual in zip(prepared_items, visuals, strict=True)
    }
    for index, row in enumerate(rows):
        if row.entity_key is None or row.entity_key not in prepared_by_key:
            continue
        prepared, visual = prepared_by_key[row.entity_key]
        image, type_icon = visual
        rows[index] = replace(
            rows[index],
            image=image,
            type_icon=type_icon,
            image_notice=(
                "官方图片暂未上线"
                if image is None and rows[index].image_layout == "square"
                else ""
            ),
        )
        if prepared.asset is not None and prepared.asset.required and image is None:
            cacheable = False

    document = present_new_content_menu(
        snapshot.weekly_cycle,
        rows,
        await _load_skill_type_icons(images, prepared_items, visuals),
        menu_title,
    )
    result = await render_new_content_document(render_html, document)
    if cacheable:
        cache.put("new_content", request_key, result)
    return result


def _with_mount_fallback(
    data: SeerDataAccess,
    prepared: NewContentPreparedItem,
) -> NewContentPreparedItem:
    asset = prepared.asset
    if prepared.item.category != "mount" or asset is None:
        return prepared
    return replace(
        prepared,
        asset=replace(
            asset,
            fallback_data=load_flash_mount_image(data, prepared.item.entity_id),
        ),
    )


def _cache_key(  # noqa: PLR0913
    snapshot: NewContentSnapshot,
    display_categories: tuple[NewContentCategory, ...],
    focused_category: NewContentCategory | None,
    menu_title: str,
    expanded_categories: frozenset[NewContentCategory],
    auto_expand_max_items: int,
) -> str:
    return render_request_cache_key(
        "new_content",
        (
            snapshot.config_version,
            snapshot.weekly_cycle,
            display_categories,
            focused_category,
            menu_title,
            tuple(sorted(expanded_categories)),
            auto_expand_max_items,
        ),
    )


def _initial_rows(
    snapshot: NewContentSnapshot,
    display_categories: tuple[NewContentCategory, ...],
    prepared_items: tuple[NewContentPreparedItem, ...],
    focused_category: NewContentCategory | None,
    expanded_categories: frozenset[NewContentCategory],
) -> list[NewContentMenuItem]:
    if focused_category is not None:
        return [
            _content_row(str(index), prepared)
            for index, prepared in enumerate(prepared_items, start=1)
        ]
    rows: list[NewContentMenuItem] = []
    prepared_by_category = {
        category: [item for item in prepared_items if item.item.category == category]
        for category in display_categories
    }
    for index, category in enumerate(display_categories):
        code = chr(ord("a") + index)
        rows.append(
            NewContentMenuItem(
                code=code,
                name=CATEGORY_NAMES[category],
                description=format_new_content_category_count(snapshot.items_for(category)),
                metadata="",
                side_title="",
                side_description="",
                stats=(),
                stats_layout="inline",
                stats_total="",
                type_name="",
                gender_name="",
                type_icon=None,
                gender_icon=None,
                image_layout="square",
                image_notice="",
                is_category=True,
                expanded=category in expanded_categories,
                image=None,
                skill=None,
                friend_skill=None,
            )
        )
        if category in expanded_categories:
            rows.extend(
                _content_row(f"{code}{item_index}", prepared)
                for item_index, prepared in enumerate(
                    prepared_by_category[category], start=1
                )
            )
    return rows


def _content_row(code: str, prepared: NewContentPreparedItem) -> NewContentMenuItem:
    details = prepared.details
    return NewContentMenuItem(
        code=code,
        name=prepared.item.name,
        description=details.description,
        metadata=details.metadata,
        side_title=details.side_title,
        side_description=details.side_description,
        stats=details.stats,
        stats_layout=details.stats_layout,
        stats_total=details.stats_total,
        type_name=details.type_name,
        gender_name=details.gender_name,
        type_icon=None,
        gender_icon=_gender_icon_data_uri(details.gender_id),
        image_layout=(
            prepared.asset.layout if prepared.asset is not None else "square"
        ),
        image_notice="",
        is_category=False,
        expanded=False,
        image=None,
        skill=details.skill,
        friend_skill=details.friend_skill,
        entity_key=(prepared.item.category, prepared.item.entity_id),
    )


async def _item_visuals(
    images: SeerImageSource,
    prepared: NewContentPreparedItem,
) -> tuple[str | None, str | None]:
    image, type_icon = await asyncio.gather(
        _asset_data_uri(images, prepared.asset),
        _type_icon(images, prepared.details.type_id),
    )
    return image, type_icon


async def _asset_data_uri(
    images: SeerImageSource,
    request: NewContentAssetRequest | None,
) -> str | None:
    if request is None:
        return None
    try:
        if request.url:
            return to_data_uri(await images.fetch_url(request.url))
        if request.kind and request.key:
            return to_data_uri(
                await images.fetch(request.kind, request.key, fallback=False)  # type: ignore[arg-type]
            )
    except (ImageSourceError, RuntimeError, TypeError, ValueError):
        if request.fallback_data is not None:
            return to_data_uri(request.fallback_data)
        return None
    return None


async def _type_icon(
    images: SeerImageSource,
    type_id: int | str | None,
) -> str | None:
    if type_id is None:
        return None
    try:
        return to_data_uri(
            await images.fetch("element_type", str(type_id), fallback=False)  # type: ignore[arg-type]
        )
    except ImageSourceError:
        return None


async def _load_skill_type_icons(
    images: SeerImageSource,
    prepared_items: tuple[NewContentPreparedItem, ...],
    visuals: list[tuple[str | None, str | None]],
) -> dict[int | str, str]:
    """Build the icon map expected by the shared pet skill-card macro."""

    type_icons: dict[int | str, str] = {"prop": ""}
    has_attribute_skill = False
    for prepared, (_image, type_icon) in zip(prepared_items, visuals, strict=True):
        skill = prepared.details.skill
        if skill is None:
            continue
        type_icons[skill["type_id"]] = type_icon or ""
        has_attribute_skill |= skill["category_id"] == SKILL_CATEGORY_ATTRIBUTE
    if has_attribute_skill:
        type_icons["prop"] = await _type_icon(images, "prop") or ""
    return type_icons


def _gender_icon_data_uri(gender_id: int | None) -> str | None:
    if gender_id is None:
        return None
    icon_path = PET_INFO_IMAGES_PATH / f"{gender_id}.png"
    if not icon_path.exists():
        icon_path = PET_INFO_IMAGES_PATH / "0.png"
    return to_data_uri(icon_path.read_bytes())
