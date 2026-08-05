# SPDX-License-Identifier: GPL-3.0-or-later
"""Materialize and render a prepared release-level new-content menu."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from typing import TYPE_CHECKING

from ironsbot.services.seer.images import (
    ImageSourceError,
    SeerImageSource,
    to_data_uri,
)
from ironsbot.services.seer.new_content import (
    CATEGORY_NAMES,
    NewContentCategory,
    NewContentSnapshot,
)
from ironsbot.services.seer.render_paths import PET_INFO_IMAGES_PATH
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
) -> bytes:
    """Render a release menu after all database state is frozen in a snapshot."""

    content_key = _cache_key(snapshot, display_categories, focused_category)
    if cached := cache.get("new_content", content_key):
        return cached

    # All ORM and domain-service reads complete before the first await below.
    prepared_items = NewContentSnapshotBuilder(data, autocard).prepare(
        snapshot,
        focused_category,
    )
    rows = _initial_rows(snapshot, display_categories, prepared_items, focused_category)
    visuals = await asyncio.gather(
        *(_item_visuals(images, prepared) for prepared in prepared_items)
    )

    cacheable = True
    for index, (prepared, (image, type_icon)) in enumerate(
        zip(prepared_items, visuals, strict=True)
    ):
        rows[index] = replace(rows[index], image=image, type_icon=type_icon)
        if prepared.asset is not None and prepared.asset.required and image is None:
            cacheable = False

    document = present_new_content_menu(
        snapshot.weekly_cycle,
        rows,
        await _load_skill_type_icons(images, prepared_items, visuals),
    )
    result = await render_new_content_document(render_html, document)
    if cacheable:
        cache.put("new_content", content_key, result)
    return result


def _initial_rows(
    snapshot: NewContentSnapshot,
    display_categories: tuple[NewContentCategory, ...],
    prepared_items: tuple[NewContentPreparedItem, ...],
    focused_category: NewContentCategory | None,
) -> list[NewContentMenuItem]:
    if focused_category is not None:
        return [
            _content_row(str(index), prepared)
            for index, prepared in enumerate(prepared_items, start=1)
        ]
    return [
        NewContentMenuItem(
            code=chr(ord("a") + index),
            name=CATEGORY_NAMES[category],
            description=f"{len(snapshot.items_for(category))} 项",
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
            is_category=True,
            expanded=False,
            image=None,
            skill=None,
            friend_skill=None,
        )
        for index, category in enumerate(display_categories)
    ]


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
        is_category=False,
        expanded=False,
        image=None,
        skill=details.skill,
        friend_skill=details.friend_skill,
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


def _cache_key(
    snapshot: NewContentSnapshot,
    categories: tuple[NewContentCategory, ...],
    focused_category: NewContentCategory | None,
) -> str:
    raw = "|".join(
        (
            snapshot.config_version,
            ",".join(categories),
            focused_category or "root",
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
