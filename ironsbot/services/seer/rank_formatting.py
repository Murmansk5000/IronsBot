# SPDX-License-Identifier: GPL-3.0-or-later
from dataclasses import dataclass

from ironsbot.services.seer.rank_models import (
    BookBreakdownSummary,
    PlayerRankSummary,
    RankLookupResult,
)


@dataclass(frozen=True, slots=True)
class RankPositionTextStyle:
    ranked_prefix: str = "全服第"
    ranked_suffix: str = ""
    unranked_prefix: str = "全服未进入前"
    unranked_suffix: str = ""
    include_zero_limit: bool = False


GLOBAL_RANK_POSITION_STYLE = RankPositionTextStyle()
RANK_LOOKUP_POSITION_STYLE = RankPositionTextStyle(
    ranked_prefix="第 ",
    ranked_suffix=" 名",
    unranked_prefix="前 ",
    unranked_suffix=" 名未上榜",
    include_zero_limit=True,
)
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

    if result.rank is not None:
        return f"{style.ranked_prefix}{result.rank}{style.ranked_suffix}"

    if result.queried and (style.include_zero_limit or result.searched_limit > 0):
        return f"{style.unranked_prefix}{result.searched_limit}{style.unranked_suffix}"

    return ""


def format_rank_lookup(result: RankLookupResult) -> str:
    if not result.queried:
        return f"{result.title}：未查询"

    if result.rank is None:
        suffix = (
            ""
            if result.score is None
            else f"（{result.score_name}：{result.score}）"
        )
        return f"{result.title}：前 {result.searched_limit} 名未上榜{suffix}"

    position_text = format_rank_position_text(
        result,
        style=RANK_LOOKUP_POSITION_STYLE,
    )
    return f"{result.title}：{position_text}（{result.score_name}：{result.score}）"


def format_peak_rank_lookup(result: RankLookupResult, *, inactive_text: str) -> str:
    if not result.queried and result.score is None:
        return inactive_text
    if not result.queried:
        return "未查询"
    return (
        format_rank_position_text(
            result,
            style=RANK_LOOKUP_POSITION_STYLE,
        )
        or "未查询"
    )


def _format_score_rank(result: RankLookupResult | None) -> str:
    if result is None or not result.queried:
        return "未查询"

    position_text = format_rank_position_text(
        result,
        style=RANK_LOOKUP_POSITION_STYLE,
    )

    if result.score is None:
        return position_text or "未查询"

    return f"{result.score}（{position_text}）" if position_text else str(result.score)


def format_book_breakdown(summary: BookBreakdownSummary) -> str:
    outfit_count = summary.outfit_count
    outfit_text = "未知"
    if outfit_count is not None:
        outfit_text = (
            f"{outfit_count}"
            f"（套装 {_format_score_rank(summary.outfit_suit)}；"
            f"部件 {_format_score_rank(summary.outfit_part)}；未找到合并总榜）"
        )

    unlocked_count = summary.unlocked_count
    unlocked_line = (
        "已解锁图鉴条目：未知"
        if unlocked_count is None
        else f"已解锁图鉴条目：{unlocked_count}"
    )

    return "\n".join(
        (
            "【图鉴条目拆分】",
            f"精灵图鉴：{_format_score_rank(summary.pet_kind)}",
            f"皮肤图鉴：{_format_score_rank(summary.skin)}",
            f"装扮图鉴：{outfit_text}",
            f"座驾图鉴：{_format_score_rank(summary.mount)}",
            f"刻印图鉴：{_format_score_rank(summary.countermark)}",
            unlocked_line,
        )
    )


def format_player_rank_summary(summary: PlayerRankSummary) -> str:
    return "\n".join(
        (
            "【全服排行】",
            format_rank_lookup(summary.book),
            format_rank_lookup(summary.achieve),
            "",
            format_book_breakdown(summary.breakdown),
        )
    )


__all__ = [
    "GLOBAL_RANK_MISS_POSITION_STYLE",
    "GLOBAL_RANK_POSITION_STYLE",
    "RANK_LOOKUP_POSITION_STYLE",
    "RankPositionTextStyle",
    "format_book_breakdown",
    "format_peak_rank_lookup",
    "format_player_rank_summary",
    "format_rank_lookup",
    "format_rank_position_text",
]
