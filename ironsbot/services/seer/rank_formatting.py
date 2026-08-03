# SPDX-License-Identifier: GPL-3.0-or-later
from dataclasses import dataclass

from ironsbot.services.seer.rank_models import RankLookupResult


@dataclass(frozen=True, slots=True)
class RankPositionTextStyle:
    ranked_prefix: str = "全服第"
    ranked_suffix: str = ""
    unranked_prefix: str = "全服未进入前"
    unranked_suffix: str = ""
    include_zero_limit: bool = False


GLOBAL_RANK_POSITION_STYLE = RankPositionTextStyle()
GLOBAL_RANK_MISS_POSITION_STYLE = RankPositionTextStyle(
    unranked_prefix="前 ",
    unranked_suffix=" 名未上榜",
    include_zero_limit=True,
)


def format_rank_position_text(
    result: RankLookupResult | None,
    *,
    style: RankPositionTextStyle = GLOBAL_RANK_POSITION_STYLE,
) -> str:
    if result is None:
        return ""

    if result.excluded:
        return "不参与公开榜单"

    if result.rank is not None:
        return f"{style.ranked_prefix}{result.rank}{style.ranked_suffix}"

    if result.queried and (style.include_zero_limit or result.searched_limit > 0):
        return f"{style.unranked_prefix}{result.searched_limit}{style.unranked_suffix}"

    return ""
