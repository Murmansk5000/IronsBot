# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from typing import TYPE_CHECKING, TypedDict, cast

from nonebot_plugin_htmlkit import template_to_pic
from seerapi_models.element_type import TypeCombinationORM
from sqlalchemy.orm import object_session

from ._cache import render_cache
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


async def render_type_matchup(target: TypeCombinationORM) -> bytes:
    """渲染属性克制面板图片，返回 PNG 图片字节。

    包含攻击效果和被攻击效果两个区域。
    """
    cached = render_cache.get("type_matchup", str(target.id))
    if cached is not None:
        return cached

    session = cast("Session | None", object_session(target))
    assert session is not None

    attack_table = calc_attack_table(session, target)
    defense_table = calc_defense_table(session, target)

    all_combo_ids: dict[int, None] = {target.id: None}
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
            "type_icon": icon_map[target.id],
            "attack_items": attack_items,
            "defense_items": defense_items,
            "cell_size": CELL_SIZE,
            "cell_gap": CELL_GAP,
        },
        max_width=MAX_WIDTH,
        allow_refit=False,
    )
    render_cache.put("type_matchup", str(target.id), result)
    return result
