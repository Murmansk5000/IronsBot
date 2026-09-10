# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ironsbot.services.seer.player_formatting_common import (
    METRIC_SEPARATOR,
    format_local_rank_suffix,
    format_peak_rank_text,
    format_player_data_time,
    format_player_identity,
    format_rank_cache_fallback,
    format_rank_star_compact,
    format_win_rate,
    join_metric_parts,
)

logger = logging.getLogger("ironsbot.services.seer.peak_diagnostics")

if TYPE_CHECKING:
    from ironsbot.services.seer.local_rank_models import LocalRankSummary
    from ironsbot.services.seer.rank_models import (
        PeakSeasonRankSummary,
        RankLookupResult,
    )
    from ironsbot.services.seer.sequ_extra import UnityPeakInfo


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
    cached_fallback = format_rank_cache_fallback(rank_result)
    if cached_fallback:
        rank_text = f"{format_peak_rank_text(rank_result.rank)}（{cached_fallback}）"
    elif failure:
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


def format_compact_peak_section(  # noqa: PLR0913
    peak: UnityPeakInfo,
    peak_rank_summary: PeakSeasonRankSummary,
    local_summary: LocalRankSummary,
    *,
    player_id: int | None = None,
    nick: str | None = None,
    nick_error: str | None = None,
    available_modes: frozenset[str] | None = None,
    mode_errors: dict[str, str] | None = None,
    query_id: str = "-",
) -> str:
    lines = ["【巅峰之战】", format_player_data_time()]
    if player_id is not None:
        lines.append(format_player_identity(player_id, nick, nick_error))

    resolved_modes = (
        available_modes
        if available_modes is not None
        else frozenset(("standard", "wild", "expert"))
    )
    errors = mode_errors or {}

    def unavailable_text(mode: str, *, current: bool = False) -> str:
        prefix = "当前" if current else ""
        return f"{prefix}暂未获取（{errors.get(mode, '查询未完成')}）"

    standard_score = peak.current_j_rank * 100_000 + peak.current_j_star
    wild_score = peak.current_k_rank * 100_000 + peak.current_k_star
    standard_available = "standard" in resolved_modes
    wild_available = "wild" in resolved_modes
    expert_available = "expert" in resolved_modes
    standard_current = (
        format_rank_star_compact(peak.current_j_rank, peak.current_j_star)
        if standard_available
        else unavailable_text("standard", current=True)
    )
    wild_current = (
        format_rank_star_compact(peak.current_k_rank, peak.current_k_star)
        if wild_available
        else unavailable_text("wild", current=True)
    )
    expert_current = (
        f"{peak.current_z_score}分"
        if expert_available
        else unavailable_text("expert", current=True)
    )

    for mode, available, profile_score, rank_result, selected in (
        (
            "standard",
            standard_available,
            standard_score,
            peak_rank_summary.standard,
            standard_current,
        ),
        ("wild", wild_available, wild_score, peak_rank_summary.wild, wild_current),
        (
            "expert",
            expert_available,
            peak.current_z_score,
            peak_rank_summary.expert,
            expert_current,
        ),
    ):
        logger.info(
            "peak display query=%s player_id=%s mode=%s profile_available=%s "
            "profile_score=%s rank_query=%s rank=%s rank_score=%s "
            "rank_queried=%s searched_limit=%s rank_failure=%s selected=%s",
            query_id,
            player_id,
            mode,
            available,
            profile_score if available else None,
            rank_result.query_id,
            rank_result.rank,
            rank_result.score,
            rank_result.queried,
            rank_result.searched_limit,
            rank_result.failure,
            selected,
        )

    lines.extend(
        [
            format_peak_line(
                "竞技",
                current=standard_current,
                history=(
                    format_rank_star_compact(peak.history_j_rank, peak.history_j_star)
                    if standard_available
                    else unavailable_text("standard")
                ),
                match_count=peak.current_j_all if standard_available else 0,
                win_rate=(
                    format_win_rate(peak.current_j_win, peak.current_j_all)
                    if standard_available and peak.current_j_all > 0
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
                history=(
                    format_rank_star_compact(peak.history_k_rank, peak.history_k_star)
                    if wild_available
                    else unavailable_text("wild")
                ),
                match_count=peak.current_k_all if wild_available else 0,
                win_rate=(
                    format_win_rate(peak.current_k_win, peak.current_k_all)
                    if wild_available and peak.current_k_all > 0
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
                history=(
                    f"{peak.history_z_score}分"
                    if expert_available
                    else unavailable_text("expert")
                ),
                match_count=peak.current_z_all if expert_available else 0,
                win_rate=(
                    format_win_rate(peak.current_z_win, peak.current_z_all)
                    if expert_available and peak.current_z_all > 0
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
