# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from typing import TYPE_CHECKING, TypedDict

from nonebot_plugin_htmlkit import template_to_pic

from ironsbot.plugins.seer_data.image import ElementTypeImageGetter, PetHeadImageGetter
from ironsbot.utils import time

from ._common import TEMPLATES_PATH, to_data_uri

if TYPE_CHECKING:
    from seerapi_models.pet import PetORM

    from ironsbot.plugins.headless_seer.game import PeakItemData
    from ironsbot.plugins.headless_seer.packets.peak import DailyRankInfo

TEMPLATE_PATH = TEMPLATES_PATH / "peak_pet_rank"
SHARED_PATH = TEMPLATES_PATH / "_shared"

TABLE_WIDTH = 580
CONTAINER_PADDING = 20 * 2


class PickRankDict(TypedDict):
    rank: int
    pet_id: int
    name: str
    count: int
    win: int
    win_rate: float
    head_img: str
    type_icon: str


class BanRankDict(TypedDict):
    rank: int
    pet_id: int
    name: str
    score: int
    head_img: str
    type_icon: str


def _get_pet_info(
    pet: "PetORM | None",
    fallback_name: str,
    head_data_uris: dict[str, str],
    type_data_uris: dict[int, str],
) -> tuple[str, str, str]:
    """返回 (name, head_img, type_icon)"""
    if pet is not None:
        return (
            pet.name,
            head_data_uris.get(str(pet.resource_id), ""),
            type_data_uris.get(pet.type.id, ""),
        )
    return fallback_name, "", ""


async def render_peak_pet_rank(
    title: str,
    pick_items: "list[PeakItemData]",
    ban_items: "list[DailyRankInfo]",
    pet_map: "dict[int, PetORM]",
) -> bytes:
    """渲染巅峰精灵榜图片，返回 PNG 图片字节"""
    unique_rids: dict[str, None] = {}
    unique_type_ids: dict[int, None] = {}

    all_ids = {item.id for item in pick_items} | {item.id for item in ban_items}
    for pet_id in all_ids:
        pet = pet_map.get(pet_id)
        if pet is not None:
            unique_rids.setdefault(str(pet.resource_id), None)
            unique_type_ids.setdefault(pet.type.id, None)

    rid_list = list(unique_rids)
    type_id_list = list(unique_type_ids)

    results = await asyncio.gather(
        *(PetHeadImageGetter.get_bytes(rid) for rid in rid_list),
        *(ElementTypeImageGetter.get_bytes(str(tid)) for tid in type_id_list),
    )

    head_bytes_list = results[: len(rid_list)]
    type_bytes_list = results[len(rid_list) :]

    head_data_uris: dict[str, str] = {
        rid: to_data_uri(data)
        for rid, data in zip(rid_list, head_bytes_list, strict=True)
    }
    type_data_uris: dict[int, str] = {
        tid: to_data_uri(data)
        for tid, data in zip(type_id_list, type_bytes_list, strict=True)
    }

    pick_ranks: list[PickRankDict] = []
    for i, item in enumerate(pick_items, 1):
        name, head_img, type_icon = _get_pet_info(
            pet_map.get(item.id), str(item.id), head_data_uris, type_data_uris
        )
        pick_ranks.append(
            {
                "rank": i,
                "pet_id": item.id,
                "name": name,
                "count": item.count,
                "win": item.win,
                "win_rate": item.win_rate,
                "head_img": head_img,
                "type_icon": type_icon,
            }
        )

    ban_ranks: list[BanRankDict] = []
    for i, item in enumerate(ban_items, 1):
        name, head_img, type_icon = _get_pet_info(
            pet_map.get(item.id), item.nick, head_data_uris, type_data_uris
        )
        ban_ranks.append(
            {
                "rank": i,
                "pet_id": item.id,
                "name": name,
                "score": item.score,
                "head_img": head_img,
                "type_icon": type_icon,
            }
        )

    return await template_to_pic(
        template_path=[TEMPLATE_PATH, SHARED_PATH],
        template_name="template.html.j2",
        templates={
            "title": title,
            "pick_ranks": pick_ranks,
            "ban_ranks": ban_ranks,
            "generated_at": time.now(tz=time.TZ_CN).strftime("%Y-%m-%d %H:%M"),
        },
        max_width=TABLE_WIDTH + CONTAINER_PADDING + 20,
        allow_refit=False,
    )
