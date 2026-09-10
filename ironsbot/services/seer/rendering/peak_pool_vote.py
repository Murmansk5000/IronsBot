# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from typing import TYPE_CHECKING, TypedDict

from ironsbot.core import time
from ironsbot.services.seer.images import SeerImageSource, to_data_uri
from ironsbot.services.seer.render_paths import (
    PEAK_POOL_VOTE_TEMPLATE_PATH,
    SHARED_TEMPLATE_PATH,
)

from . import HtmlTemplateRenderer

if TYPE_CHECKING:
    from ironsbot.services.seer.peak import PeakPetSnapshot
    from ironsbot.services.seer.rank_models import RankEntry

TABLE_WIDTH = 900
CONTAINER_PADDING = 20 * 2


class VoteRankDict(TypedDict):
    rank: int
    pet_id: int
    name: str
    score: int
    percentage: int
    head_img: str
    type_icon: str


class VotePoolDict(TypedDict):
    title: str
    period: str
    total_votes: int
    ranks: list[VoteRankDict]


class VotePoolInput(TypedDict):
    items: "list[RankEntry]"
    title: str
    period: str
    pets: "list[PeakPetSnapshot]"


async def render_peak_pool_vote(
    images: SeerImageSource,
    render_html: HtmlTemplateRenderer,
    pools: list[VotePoolInput],
) -> bytes:
    """渲染巅峰池票选结果图片，返回 PNG 图片字节"""
    pet_map: dict[int, "PeakPetSnapshot"] = {}
    unique_rids: dict[str, None] = {}
    unique_type_ids: dict[int, None] = {}

    for pool in pools:
        for pet in pool["pets"]:
            pet_map[pet.id] = pet
            unique_rids.setdefault(str(pet.resource_id), None)
            unique_type_ids.setdefault(pet.type_id, None)

    rid_list = list(unique_rids)
    type_id_list = list(unique_type_ids)

    results = await asyncio.gather(
        *(images.fetch("pet_head", rid) for rid in rid_list),
        *(images.fetch("element_type", str(tid)) for tid in type_id_list),
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
        ranks: list[VoteRankDict] = []
        total_votes = sum(max(info.score, 0) for info in pool["items"])
        for i, info in enumerate(pool["items"], 1):
            pet = pet_map.get(info.id)
            if pet is not None:
                head_img = head_data_uris[str(pet.resource_id)]
                type_icon = type_data_uris[pet.type_id]
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
                    "percentage": (
                        round(max(info.score, 0) / total_votes * 100)
                        if total_votes
                        else 0
                    ),
                    "head_img": head_img,
                    "type_icon": type_icon,
                }
            )
        pool_dicts.append(
            {
                "title": pool["title"],
                "period": pool["period"],
                "total_votes": total_votes,
                "ranks": ranks,
            }
        )

    return await render_html(
        template_path=[PEAK_POOL_VOTE_TEMPLATE_PATH, SHARED_TEMPLATE_PATH],
        template_name="template.html.j2",
        templates={
            "pools": pool_dicts,
            "generated_at": time.now(tz=time.TZ_CN).strftime("%Y-%m-%d %H:%M"),
        },
        max_width=TABLE_WIDTH + CONTAINER_PADDING + 20,
        allow_refit=False,
    )
