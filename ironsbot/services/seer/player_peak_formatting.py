# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.player_formatting_common import (
    METRIC_SEPARATOR,
    format_local_rank_suffix,
    format_peak_rank_text,
    format_player_identity,
    format_rank_star_compact,
    format_win_rate,
    join_metric_parts,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.local_rank_models import LocalRankSummary
    from ironsbot.services.seer.rank_models import PeakSeasonRankSummary
    from ironsbot.services.seer.sequ_extra import UnityPeakInfo

def format_peak_line(  # noqa: PLR0913
    title: str,
    *,
    current: str,
    history: str,
    match_count: int,
    win_rate: str,
    rank: int | None,
    local_summary: LocalRankSummary,
    score_key: str,
    win_rate_key: str,
    match_key: str,
) -> str:
    match_text = ""
    if match_count > 0:
        match_text = (
            f"场次{match_count}"
            f"{format_local_rank_suffix(local_summary, match_key, label='样本场次')}"
        )
    win_rate_text = (
        f"胜率{win_rate}"
        f"{format_local_rank_suffix(local_summary, win_rate_key, label='样本胜率')}"
    )
    rank_text = (
        f"{format_peak_rank_text(rank)}"
        f"{format_local_rank_suffix(local_summary, score_key, label='样本段位')}"
    )
    return (
        f"{title}：{current}{METRIC_SEPARATOR}历史{history}"
        f"{METRIC_SEPARATOR}"
        f"{join_metric_parts(match_text, win_rate_text, rank_text)}"
    )


def format_compact_peak_section(
    peak: UnityPeakInfo,
    peak_rank_summary: PeakSeasonRankSummary,
    local_summary: LocalRankSummary,
    *,
    player_id: int | None = None,
    nick: str | None = None,
) -> str:
    lines = ["【巅峰之战】"]
    if player_id is not None:
        lines.append(format_player_identity(player_id, nick))

    lines.extend(
        [
            format_peak_line(
                "竞技",
                current=format_rank_star_compact(
                    peak.current_j_rank,
                    peak.current_j_star,
                ),
                history=format_rank_star_compact(
                    peak.history_j_rank,
                    peak.history_j_star,
                ),
                match_count=peak.current_j_all,
                win_rate=format_win_rate(
                    peak.current_j_win,
                    peak.current_j_all,
                ),
                rank=peak_rank_summary.standard.rank,
                local_summary=local_summary,
                score_key="peak_standard",
                win_rate_key="peak_standard_win_rate",
                match_key="peak_standard_matches",
            ),
            format_peak_line(
                "狂野",
                current=format_rank_star_compact(
                    peak.current_k_rank,
                    peak.current_k_star,
                ),
                history=format_rank_star_compact(
                    peak.history_k_rank,
                    peak.history_k_star,
                ),
                match_count=peak.current_k_all,
                win_rate=format_win_rate(
                    peak.current_k_win,
                    peak.current_k_all,
                ),
                rank=peak_rank_summary.wild.rank,
                local_summary=local_summary,
                score_key="peak_wild",
                win_rate_key="peak_wild_win_rate",
                match_key="peak_wild_matches",
            ),
            format_peak_line(
                "专家",
                current=f"{peak.current_z_score}分",
                history=f"{peak.history_z_score}分",
                match_count=peak.current_z_all,
                win_rate=format_win_rate(
                    peak.current_z_win,
                    peak.current_z_all,
                ),
                rank=peak_rank_summary.expert.rank,
                local_summary=local_summary,
                score_key="peak_expert",
                win_rate_key="peak_expert_win_rate",
                match_key="peak_expert_matches",
            ),
        ]
    )
    return "\n".join(lines)
