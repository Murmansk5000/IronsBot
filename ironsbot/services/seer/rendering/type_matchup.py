# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from typing import TypedDict

from seerapi_models.element_type import TypeCombinationORM

from ironsbot.services.seer.images import SeerImageSource, to_data_uri
from ironsbot.services.seer.render_cache import RenderCache
from ironsbot.services.seer.render_paths import TYPE_MATCHUP_TEMPLATE_PATH
from ironsbot.services.seer.type_calc import TypeMatchup

from . import HtmlTemplateRenderer

GRID_COLUMNS = 10
CELL_SIZE = 72
CELL_GAP = 6
SECTION_OVERHEAD = 16 * 2 + 1 * 2  # section padding + border
CONTAINER_PADDING = 20 * 2
GRID_WIDTH = GRID_COLUMNS * CELL_SIZE + (GRID_COLUMNS - 1) * CELL_GAP
MAX_WIDTH = GRID_WIDTH + SECTION_OVERHEAD + CONTAINER_PADDING


class MatchupItemDict(TypedDict):
    icon: str
    name: str
    multiplier: float


def _is_custom_type_combination(target: TypeCombinationORM) -> bool:
    return target.id < 0


async def _resolve_custom_target_icons(
    images: SeerImageSource,
    target: TypeCombinationORM,
    *,
    target_icon_data_uri: str | None,
    target_icon_secondary_data_uri: str | None,
) -> tuple[str, str | None]:
    """Use single-type icons for custom combinations."""
    if target.secondary_id is None:
        if target_icon_data_uri is not None:
            return target_icon_data_uri, None
        primary_bytes = await images.fetch("element_type", str(target.primary_id))
        return to_data_uri(primary_bytes), None

    if target_icon_data_uri is not None and target_icon_secondary_data_uri is not None:
        return target_icon_data_uri, target_icon_secondary_data_uri

    primary_bytes, secondary_bytes = await asyncio.gather(
        images.fetch("element_type", str(target.primary_id)),
        images.fetch("element_type", str(target.secondary_id)),
    )
    return to_data_uri(primary_bytes), to_data_uri(secondary_bytes)


async def render_type_matchup(  # noqa: PLR0913
    cache: RenderCache,
    images: SeerImageSource,
    render_html: HtmlTemplateRenderer,
    matchup: TypeMatchup,
    *,
    target_icon_data_uri: str | None = None,
    target_icon_secondary_data_uri: str | None = None,
) -> bytes:
    """渲染属性克制面板图片，返回 PNG 图片字节。

    包含攻击效果和被攻击效果两个区域，支持自定义属性组合渲染。
    """
    cached = cache.get("type_matchup", matchup.cache_key)
    if cached is not None:
        return cached

    target = matchup.target

    all_combo_ids: dict[int, None] = {}
    for combo, _ in matchup.attack_table:
        all_combo_ids.setdefault(combo.id, None)
    for combo, _ in matchup.defense_table:
        all_combo_ids.setdefault(combo.id, None)

    id_list = list(all_combo_ids)
    icon_bytes_list = await asyncio.gather(
        *(images.fetch("element_type", str(cid)) for cid in id_list)
    )
    icon_map: dict[int, str] = {
        cid: to_data_uri(data)
        for cid, data in zip(id_list, icon_bytes_list, strict=True)
    }
    type_icon_secondary: str | None = None
    if _is_custom_type_combination(target):
        target_icon_data_uri, type_icon_secondary = await _resolve_custom_target_icons(
            images,
            target,
            target_icon_data_uri=target_icon_data_uri,
            target_icon_secondary_data_uri=target_icon_secondary_data_uri,
        )
    else:
        if target_icon_data_uri is None:
            target_icon_data_uri = icon_map.get(target.id)
        if target_icon_data_uri is None:
            target_icon_data_uri = to_data_uri(
                await images.fetch("element_type", str(target.id))
            )

    attack_items: list[MatchupItemDict] = sorted(
        [
            {"icon": icon_map[combo.id], "name": combo.name, "multiplier": mult}
            for combo, mult in matchup.attack_table
        ],
        key=lambda x: x["multiplier"],
        reverse=True,
    )
    defense_items: list[MatchupItemDict] = sorted(
        [
            {"icon": icon_map[combo.id], "name": combo.name, "multiplier": mult}
            for combo, mult in matchup.defense_table
        ],
        key=lambda x: x["multiplier"],
        reverse=True,
    )

    result = await render_html(
        template_path=TYPE_MATCHUP_TEMPLATE_PATH,
        template_name="template.html.j2",
        templates={
            "type_name": target.name,
            "type_icon": target_icon_data_uri,
            "type_icon_secondary": type_icon_secondary,
            "attack_items": attack_items,
            "defense_items": defense_items,
            "cell_size": CELL_SIZE,
            "cell_gap": CELL_GAP,
        },
        max_width=MAX_WIDTH,
        allow_refit=False,
    )
    cache.put("type_matchup", matchup.cache_key, result)
    return result
