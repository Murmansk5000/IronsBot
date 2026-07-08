# SPDX-License-Identifier: GPL-3.0-or-later
from ironsbot.services.seer.rank_models import (
    BookBreakdownSummary,
    PlayerRankSummary,
    RankLookupResult,
)


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

    return f"{result.title}：第 {result.rank} 名（{result.score_name}：{result.score}）"


def format_peak_rank_lookup(result: RankLookupResult, *, inactive_text: str) -> str:
    if not result.queried and result.score is None:
        return inactive_text
    if not result.queried:
        return "未查询"
    if result.rank is None:
        return f"前 {result.searched_limit} 名未上榜"
    return f"第 {result.rank} 名"


def _format_score_rank(result: RankLookupResult | None) -> str:
    if result is None or not result.queried:
        return "未查询"

    if result.score is None:
        return f"前 {result.searched_limit} 名未上榜"

    if result.rank is None:
        return f"{result.score}（前 {result.searched_limit} 名未上榜）"

    return f"{result.score}（第 {result.rank} 名）"


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
    "format_book_breakdown",
    "format_peak_rank_lookup",
    "format_player_rank_summary",
    "format_rank_lookup",
]

