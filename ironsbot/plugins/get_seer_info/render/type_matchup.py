# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from typing import TYPE_CHECKING, TypedDict, cast

from nonebot_plugin_htmlkit import template_to_pic
from seerapi_models.element_type import TypeCombinationORM
from sqlalchemy.orm import object_session

from ironsbot.plugins.get_seer_info.render._cache import render_cache
from ironsbot.plugins.seer_data.image import ElementTypeImageGetter

from ..type_calc import calc_attack_table, calc_defense_table
from ._common import TEMPLATES_PATH, to_data_uri

if TYPE_CHECKING:
    from sqlmodel import Session

TEMPLATE_PATH = TEMPLATES_PATH / "type_matchup"

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
    target: TypeCombinationORM,
    *,
    target_icon_data_uri: str | None,
    target_icon_secondary_data_uri: str | None,
) -> tuple[str, str | None]:
    """自定义组合使用单属性图标；双属性时返回左右各半的两张图。"""
    if target.secondary_id is None:
        if target_icon_data_uri is not None:
            return target_icon_data_uri, None
        primary_bytes = await ElementTypeImageGetter.get_bytes(str(target.primary_id))
        return to_data_uri(primary_bytes), None

    if (
        target_icon_data_uri is not None
        and target_icon_secondary_data_uri is not None
    ):
        return target_icon_data_uri, target_icon_secondary_data_uri

    primary_bytes, secondary_bytes = await asyncio.gather(
        ElementTypeImageGetter.get_bytes(str(target.primary_id)),
        ElementTypeImageGetter.get_bytes(str(target.secondary_id)),
    )
    return to_data_uri(primary_bytes), to_data_uri(secondary_bytes)


async def render_type_matchup(
    target: TypeCombinationORM,
    *,
    session: "Session | None" = None,
    cache_key: str | None = None,
    target_icon_data_uri: str | None = None,
    target_icon_secondary_data_uri: str | None = None,
) -> bytes:
    """渲染属性克制面板图片，返回 PNG 图片字节。

    包含攻击效果和被攻击效果两个区域，支持自定义属性组合渲染。
    """
    resolved_cache_key = cache_key if cache_key is not None else str(target.id)
    cached = render_cache.get("type_matchup", resolved_cache_key)
    if cached is not None:
        return cached

    resolved_session = session
    if resolved_session is None:
        resolved_session = cast("Session | None", object_session(target))
    assert resolved_session is not None

    attack_table = calc_attack_table(resolved_session, target)
    defense_table = calc_defense_table(resolved_session, target)

    all_combo_ids: dict[int, None] = {}
    for combo, _ in attack_table:
        all_combo_ids.setdefault(combo.id, None)
    for combo, _ in defense_table:
        all_combo_ids.setdefault(combo.id, None)

    id_list = list(all_combo_ids)
    icon_bytes_list = await asyncio.gather(
        *(ElementTypeImageGetter.get_bytes(str(cid)) for cid in id_list)
    )
    icon_map: dict[int, str] = {
        cid: to_data_uri(data)
        for cid, data in zip(id_list, icon_bytes_list, strict=True)
    }
    type_icon_secondary: str | None = None
    if _is_custom_type_combination(target):
        target_icon_data_uri, type_icon_secondary = await _resolve_custom_target_icons(
            target,
            target_icon_data_uri=target_icon_data_uri,
            target_icon_secondary_data_uri=target_icon_secondary_data_uri,
        )
    else:
        if target_icon_data_uri is None:
            target_icon_data_uri = icon_map.get(target.id)
        if target_icon_data_uri is None:
            target_icon_data_uri = to_data_uri(
                await ElementTypeImageGetter.get_bytes(str(target.id))
            )

    attack_items: list[MatchupItemDict] = sorted(
        [
            {"icon": icon_map[combo.id], "name": combo.name, "multiplier": mult}
            for combo, mult in attack_table
        ],
        key=lambda x: x["multiplier"],
        reverse=True,
    )
    defense_items: list[MatchupItemDict] = sorted(
        [
            {"icon": icon_map[combo.id], "name": combo.name, "multiplier": mult}
            for combo, mult in defense_table
        ],
        key=lambda x: x["multiplier"],
        reverse=True,
    )

    result = await template_to_pic(
        template_path=TEMPLATE_PATH,
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
    render_cache.put("type_matchup", resolved_cache_key, result)
    return result
