# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.peak_modes import PEAK_MODE_NAMES
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

if TYPE_CHECKING:
    from ironsbot.services.seer.local_rank_models import LocalRankSummary
    from ironsbot.services.seer.rank_models import (
        PeakSeasonRankSummary,
        RankLookupResult,
    )
    from ironsbot.services.seer.sequ_extra import UnityPeakInfo


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
    history_label: str = "历史",
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
        f"{title}：{current}{METRIC_SEPARATOR}{history_label}{history}"
        f"{METRIC_SEPARATOR}"
        f"{join_metric_parts(match_text, win_rate_text, rank_text)}"
    )


def format_master_peak_line(result: RankLookupResult) -> str:
    score = result.score
    score_text = _format_peak_rating_score(score) if score is not None else ""
    cached_fallback = format_rank_cache_fallback(result)
    if cached_fallback:
        rank_text = f"{format_peak_rank_text(result.rank)}（{cached_fallback}）"
    elif result.failure:
        rank_text = f"赛季榜{result.failure}"
    elif result.rank is not None:
        rank_text = format_peak_rank_text(result.rank)
    elif result.queried:
        rank_text = (
            f"赛季榜前{result.searched_limit}名未确认"
            if result.searched_limit > 0
            else "赛季榜未确认"
        )
    else:
        rank_text = "赛季榜未查询"
    return f"大师：{join_metric_parts(score_text, rank_text)}"


def format_compact_peak_section(  # noqa: PLR0913
    peak: UnityPeakInfo,
    peak_rank_summary: PeakSeasonRankSummary,
    local_summary: LocalRankSummary,
    *,
    fetched_at: float | None,
    player_id: int | None = None,
    nick: str | None = None,
    nick_error: str | None = None,
    available_modes: frozenset[str] | None = None,
    mode_errors: dict[str, str] | None = None,
) -> str:
    lines = ["【巅峰之战】", format_player_data_time(fetched_at)]
    if player_id is not None:
        lines.append(format_player_identity(player_id, nick, nick_error))

    resolved_modes = available_modes if available_modes is not None else PEAK_MODE_NAMES
    errors = mode_errors or {}

    def unavailable_text(mode: str, *, current: bool = False) -> str:
        prefix = "当前" if current else ""
        return f"{prefix}暂未获取（{errors.get(mode, '查询未完成')}）"

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
            format_peak_line(
                "大师",
                history_label="赛季最高",
                current=(
                    format_rank_star_compact(peak.current_m_rank, peak.current_m_star)
                    if "master" in resolved_modes
                    else unavailable_text("master", current=True)
                ),
                history=(
                    format_rank_star_compact(peak.history_m_rank, peak.history_m_star)
                    if "master" in resolved_modes
                    else unavailable_text("master")
                ),
                match_count=(peak.current_m_all or 0)
                if "master" in resolved_modes
                else 0,
                win_rate=(
                    format_win_rate(peak.current_m_win, peak.current_m_all)
                    if "master" in resolved_modes and peak.current_m_all
                    else ""
                ),
                rank_result=peak_rank_summary.master,
                local_summary=local_summary,
                score_key="peak_master",
                win_rate_key="peak_master_win_rate",
                match_key="peak_master_matches",
            ),
        ]
    )
    if "master" in resolved_modes and peak.current_m_all is None:
        lines.append(f"大师胜场：{peak.current_m_win}｜场次及胜率暂无法确认")
    if resolved_modes == PEAK_MODE_NAMES and peak.current_m_all is not None:
        total = (
            peak.current_j_all
            + peak.current_k_all
            + peak.current_z_all
            + peak.current_m_all
        )
        lines.append(f"巅峰总场次：{total}场（各模式当前赛季合计）")
    return "\n".join(lines)
