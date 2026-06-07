# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from typing import TYPE_CHECKING, TypedDict

from nonebot_plugin_htmlkit import template_to_pic

from ironsbot.plugins.seer_data.image import ElementTypeImageGetter, PetHeadImageGetter
from ironsbot.utils import time

from ._common import TEMPLATES_PATH, to_data_uri

if TYPE_CHECKING:
    from seerapi_models.pet import PetORM

    from ironsbot.plugins.headless_seer.packets.peak import DailyRankList

TEMPLATE_PATH = TEMPLATES_PATH / "peak_pool_vote"
SHARED_PATH = TEMPLATES_PATH / "_shared"

TABLE_WIDTH = 400
CONTAINER_PADDING = 20 * 2


class VoteRankDict(TypedDict):
    rank: int
    pet_id: int
    name: str
    score: int
    head_img: str
    type_icon: str


class VotePoolDict(TypedDict):
    title: str
    ranks: list[VoteRankDict]


class VotePoolInput(TypedDict):
    content: "DailyRankList"
    title: str
    pets: "list[PetORM]"


async def render_peak_pool_vote(pools: list[VotePoolInput]) -> bytes:
    """渲染巅峰池票选结果图片，返回 PNG 图片字节"""
    pet_map: dict[int, "PetORM"] = {}
    unique_rids: dict[str, None] = {}
    unique_type_ids: dict[int, None] = {}

    for pool in pools:
        for pet in pool["pets"]:
            pet_map[pet.id] = pet
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

    pool_dicts: list[VotePoolDict] = []
    for pool in pools:
        rank_list = pool["content"].rank_list
        ranks: list[VoteRankDict] = []
        for i, info in enumerate(rank_list, 1):
            pet = pet_map.get(info.id)
            if pet is not None:
                head_img = head_data_uris[str(pet.resource_id)]
                type_icon = type_data_uris[pet.type.id]
                name = pet.name
            else:
                head_img = ""
                type_icon = ""
                name = info.nick
            ranks.append(
                {
                    "rank": i,
                    "pet_id": info.id,
                    "name": name,
                    "score": info.score,
                    "head_img": head_img,
                    "type_icon": type_icon,
                }
            )
        pool_dicts.append(
            {
                "title": pool["title"],
                "ranks": ranks,
            }
        )

    return await template_to_pic(
        template_path=[TEMPLATE_PATH, SHARED_PATH],
        template_name="template.html.j2",
        templates={
            "pools": pool_dicts,
            "generated_at": time.now(tz=time.TZ_CN).strftime("%Y-%m-%d %H:%M"),
        },
        max_width=TABLE_WIDTH + CONTAINER_PADDING + 20,
        allow_refit=False,
    )
