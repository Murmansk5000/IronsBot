# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.rank_catalog import rank_command_names
from ironsbot.services.seer.rank_list_models import (
    GLOBAL_RANKS,
    LOCAL_RANKS,
    GlobalRankSpec,
    LocalRankSpec,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

def _rank_titles(
    kind: str,
    ranks: Mapping[str, GlobalRankSpec | LocalRankSpec],
) -> str:
    titles: list[str] = []
    for key, spec in ranks.items():
        try:
            title = rank_command_names(kind, key)[0]
        except KeyError:
            # Tests may supply a deliberately small synthetic rank catalog.
            title = spec.title
        titles.append(title)
    return "、".join(titles)


def format_rank_help(
    command_help: str,
    *,
    global_ranks: Mapping[str, GlobalRankSpec] = GLOBAL_RANKS,
    local_ranks: Mapping[str, LocalRankSpec] = LOCAL_RANKS,
) -> str:
    """Format the rank catalog and command forms guaranteed by its parsers."""

    global_titles = _rank_titles("global", global_ranks)
    local_titles = _rank_titles("local", local_ranks)
    sections = (
        "【查询格式】\n"
        "成就榜：按默认条数显示\n"
        "成就榜200名：查询指定名次\n"
        "成就榜第2页：按默认条数翻页\n"
        "成就榜21-40：查询指定范围\n"
        "成就榜123456789、成就榜玩家别名：查询该玩家在全服榜的名次\n"
        "成就榜5000点、群星牌榜3149分：按分数反查全服榜\n"
        "竞技段位榜王者0星：按段位分数反查\n"
        "样本皮肤榜21-40：查询样本榜范围",
        f"【全服榜】\n{global_titles}",
        f"【样本榜】\n{local_titles}",
        "【刻印数值榜】\n"
        "默认查询全部角数；可查物攻、物防、特攻、特防、速度、体力、双防、双攻、盾、双刀、总和，"
        "也可组合属性。\n"
        "示例：刻印攻击榜、六角双攻榜、特攻双防刻印榜、刻印双防体榜",
    )
    if command_help:
        return "\n\n".join((*sections, command_help))
    return "\n\n".join(sections)
