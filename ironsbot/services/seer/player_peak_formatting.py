# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.player_formatting_common import (
    METRIC_SEPARATOR,
    format_local_rank_suffix,
    format_peak_rank_text,
    format_player_data_time,
    format_player_identity,
    format_rank_star_compact,
    format_win_rate,
    join_metric_parts,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.services.seer.local_rank_models import LocalRankSummary
    from ironsbot.services.seer.rank_models import (
        PeakSeasonRankSummary,
        RankLookupResult,
    )
    from ironsbot.services.seer.sequ_extra import UnityPeakInfo


def _resolve_peak_current(
    result: RankLookupResult,
    *,
    score_formatter: Callable[[int], str],
) -> tuple[str, bool]:
    rank = getattr(result, "rank", None)
    score = getattr(result, "score", None)
    if rank is not None and score is not None:
        return score_formatter(int(score)), True
    return "当前赛季未确认", False


def _format_peak_rating_score(score: int) -> str:
    rank, star = divmod(score, 100_000)
    return format_rank_star_compact(rank, star)


def format_peak_line(  # noqa: PLR0913
    title: str,
    *,
    current: str,
    history: str,
    match_count: int,
    win_rate: str,
    rank_result: RankLookupResult,
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
    win_rate_text = ""
    if win_rate:
        win_rate_text = (
            f"胜率{win_rate}"
            f"{format_local_rank_suffix(local_summary, win_rate_key, label='样本胜率')}"
        )
    failure = rank_result.failure
    if failure:
        rank_text = f"赛季榜{failure}"
    elif rank_result.rank is not None:
        rank_text = (
            f"{format_peak_rank_text(rank_result.rank)}"
            f"{format_local_rank_suffix(local_summary, score_key, label='样本段位')}"
        )
    elif rank_result.queried:
        rank_text = (
            f"赛季榜前{rank_result.searched_limit}名未确认"
            if rank_result.searched_limit > 0
            else "赛季榜未确认"
        )
    else:
        rank_text = "赛季榜未查询"
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
    lines = ["【巅峰之战】", format_player_data_time()]
    if player_id is not None:
        lines.append(format_player_identity(player_id, nick))

    standard_current, standard_stats_available = _resolve_peak_current(
        peak_rank_summary.standard,
        score_formatter=_format_peak_rating_score,
    )
    wild_current, wild_stats_available = _resolve_peak_current(
        peak_rank_summary.wild,
        score_formatter=_format_peak_rating_score,
    )
    expert_current, expert_stats_available = _resolve_peak_current(
        peak_rank_summary.expert,
        score_formatter=lambda score: f"{score}分",
    )

    lines.extend(
        [
            format_peak_line(
                "竞技",
                current=standard_current,
                history=format_rank_star_compact(
                    peak.history_j_rank,
                    peak.history_j_star,
                ),
                match_count=peak.current_j_all if standard_stats_available else 0,
                win_rate=(
                    format_win_rate(peak.current_j_win, peak.current_j_all)
                    if standard_stats_available
                    else ""
                ),
                rank_result=peak_rank_summary.standard,
                local_summary=local_summary,
                score_key="peak_standard",
                win_rate_key="peak_standard_win_rate",
                match_key="peak_standard_matches",
            ),
            format_peak_line(
                "狂野",
                current=wild_current,
                history=format_rank_star_compact(
                    peak.history_k_rank,
                    peak.history_k_star,
                ),
                match_count=peak.current_k_all if wild_stats_available else 0,
                win_rate=(
                    format_win_rate(peak.current_k_win, peak.current_k_all)
                    if wild_stats_available
                    else ""
                ),
                rank_result=peak_rank_summary.wild,
                local_summary=local_summary,
                score_key="peak_wild",
                win_rate_key="peak_wild_win_rate",
                match_key="peak_wild_matches",
            ),
            format_peak_line(
                "专家",
                current=expert_current,
                history=f"{peak.history_z_score}分",
                match_count=peak.current_z_all if expert_stats_available else 0,
                win_rate=(
                    format_win_rate(peak.current_z_win, peak.current_z_all)
                    if expert_stats_available
                    else ""
                ),
                rank_result=peak_rank_summary.expert,
                local_summary=local_summary,
                score_key="peak_expert",
                win_rate_key="peak_expert_win_rate",
                match_key="peak_expert_matches",
            ),
        ]
    )
    return "\n".join(lines)
