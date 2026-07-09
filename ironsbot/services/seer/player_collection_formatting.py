# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ironsbot.services.seer.player_formatting_common import (
    format_metric_line,
    join_metric_parts,
    sample_rank_text,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.local_rank_models import LocalRankSummary
    from ironsbot.services.seer.rank_models import PlayerRankSummary, RankLookupResult
    from ironsbot.services.seer.sequ_extra import UnityPartOneInfo

def format_collection_info(
    more_info: Any,
    *,
    unity_part_one: UnityPartOneInfo,
    rank_summary: PlayerRankSummary,
    local_summary: LocalRankSummary,
    player_identity: str,
) -> str:
    breakdown = rank_summary.breakdown
    outfit_suit_score = (
        None if breakdown.outfit_suit is None else breakdown.outfit_suit.score
    )
    outfit_part_score = (
        None if breakdown.outfit_part is None else breakdown.outfit_part.score
    )
    countermark_score = (
        None if breakdown.countermark is None else breakdown.countermark.score
    )

    metric_lines = [
        format_metric_line(
            "精灵数量",
            getattr(more_info, "pet_all_num", 0),
            local_summary=local_summary,
            local_key="pet_total_count",
        ),
        format_metric_line(
            "图鉴积分",
            rank_summary.book.score,
            rank_result=rank_summary.book,
            local_summary=local_summary,
            local_key="book_score",
        ),
        format_metric_line(
            "成就点数",
            getattr(more_info, "total_achieve", 0),
            rank_result=rank_summary.achieve,
            local_summary=local_summary,
            local_key="achievement_score",
        ),
        format_metric_line(
            "精灵图鉴",
            unity_part_one.pet_kind_num,
            rank_result=breakdown.pet_kind,
            local_summary=local_summary,
            local_key="pet_kind_count",
        ),
        format_metric_line(
            "皮肤图鉴",
            unity_part_one.skin_num,
            rank_result=breakdown.skin,
            local_summary=local_summary,
            local_key="skin_count",
        ),
        format_metric_line(
            "套装图鉴",
            outfit_suit_score,
            rank_result=breakdown.outfit_suit,
            local_summary=local_summary,
            local_key="outfit_suit_count",
        ),
        format_metric_line(
            "部件图鉴",
            outfit_part_score,
            rank_result=breakdown.outfit_part,
            local_summary=local_summary,
            local_key="outfit_part_count",
        ),
        format_metric_line(
            "座驾图鉴",
            None if breakdown.mount is None else breakdown.mount.score,
            rank_result=breakdown.mount,
            local_summary=local_summary,
            local_key="mount_count",
        ),
        format_metric_line(
            "刻印图鉴",
            countermark_score,
            rank_result=breakdown.countermark,
            local_summary=local_summary,
            local_key="countermark_count",
        ),
        format_metric_line(
            "已解锁图鉴条目",
            breakdown.unlocked_count,
            local_summary=local_summary,
            local_key="unlocked_book_entries",
        ),
        format_metric_line(
            "成就数量",
            unity_part_one.achievement_num,
            local_summary=local_summary,
            local_key="achievement_count",
        ),
    ]
    lines = ["📚【收集与排行】", player_identity]
    lines.extend(line for line in metric_lines if line)
    return "\n".join(lines)


def format_autocard_rank_info(
    result: RankLookupResult,
    *,
    player_identity: str,
    local_summary: LocalRankSummary,
) -> str:
    lines = ["🃏【群星牌排名】", player_identity]
    sample_text = (
        sample_rank_text(local_summary, "autocard_score")
        if result.score is not None
        else ""
    )
    if not result.queried:
        lines.append("群星之巅：未查询")
    elif result.rank is None:
        if result.score is None:
            lines.append(f"群星之巅：前 {result.searched_limit} 名未上榜")
        else:
            metric_text = join_metric_parts(
                f"{result.score}分",
                f"前 {result.searched_limit} 名未上榜",
                sample_text,
            )
            lines.append(f"群星之巅：{metric_text}")
    else:
        score_text = "未知分" if result.score is None else f"{result.score}分"
        metric_text = join_metric_parts(
            score_text,
            f"全服第{result.rank}",
            sample_text,
        )
        lines.append(f"群星之巅：{metric_text}")
    return "\n".join(lines)
