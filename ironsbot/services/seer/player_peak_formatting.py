# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.peak_modes import PEAK_MODE_NAMES, valid_peak_counts
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
    from ironsbot.services.seer.sequ_extra import PeakField, UnityPeakInfo


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
    invalid_counts: bool = False,
    match_detail: str = "",
) -> str:
    match_text = ""
    if invalid_counts:
        match_text = "场次数据异常"
    elif match_count > 0:
        match_text = (
            f"场次{match_count}"
            f"{format_local_rank_suffix(local_summary, match_key, label='样本场次')}"
        )
    win_rate_text = ""
    match_text = join_metric_parts(match_text, match_detail)
    if win_rate and not invalid_counts:
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
        sample_suffix = (
            format_local_rank_suffix(local_summary, score_key, label="样本段位")
            if not invalid_counts
            else ""
        )
        rank_text = f"{format_peak_rank_text(rank_result.rank)}{sample_suffix}"
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


def format_compact_peak_section(  # noqa: C901, PLR0913 - common formatting for four modes
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
    fields: dict[tuple[str, str], PeakField] | None = None,
) -> str:
    lines = ["【巅峰之战】", format_player_data_time(fetched_at)]
    if player_id is not None:
        lines.append(format_player_identity(player_id, nick, nick_error))

    resolved = available_modes if available_modes is not None else PEAK_MODE_NAMES
    errors = mode_errors or {}
    fields = fields or {}
    rows = (
        (
            "standard",
            "竞技",
            format_rank_star_compact(peak.current_j_rank, peak.current_j_star),
            format_rank_star_compact(peak.history_j_rank, peak.history_j_star),
            peak.current_j_win,
            peak.current_j_all,
            peak_rank_summary.standard,
        ),
        (
            "wild",
            "狂野",
            format_rank_star_compact(peak.current_k_rank, peak.current_k_star),
            format_rank_star_compact(peak.history_k_rank, peak.history_k_star),
            peak.current_k_win,
            peak.current_k_all,
            peak_rank_summary.wild,
        ),
        (
            "expert",
            "专家",
            f"{peak.current_z_score}分",
            f"{peak.history_z_score}分",
            peak.current_z_win,
            peak.current_z_all,
            peak_rank_summary.expert,
        ),
        (
            "master",
            "大师",
            format_rank_star_compact(peak.current_m_rank, peak.current_m_star),
            format_rank_star_compact(peak.history_m_rank, peak.history_m_star),
            peak.current_m_win,
            peak.current_m_all,
            peak_rank_summary.master,
        ),
    )
    valid_totals: list[int] = []
    for mode, title, current, history, wins, matches, rank in rows:

        def missing(name: str, *, mode: str = mode) -> str | None:
            if item := fields.get((mode, name)):
                return (
                    f"暂未获取（{item.error or '查询未完成'}）"
                    if item.value is None
                    else None
                )
            return (
                None
                if mode in resolved
                else f"暂未获取（{errors.get(mode, '查询未完成')}）"
            )

        current_missing = missing("current")
        match_missing = missing("matches")
        wins_missing = missing("wins")
        have_counts = match_missing is None and wins_missing is None
        valid = have_counts and valid_peak_counts(wins, matches)
        if valid and matches is not None:
            valid_totals.append(matches)
        match_detail = ""
        if fields:
            if match_missing:
                match_detail = f"场次{match_missing}"
            elif matches == 0 and (wins_missing or wins == 0):
                match_detail = "场次0"
            if wins_missing:
                win_detail = f"胜场{wins_missing}"
                match_detail = join_metric_parts(match_detail, win_detail)
            elif match_missing:
                match_detail = join_metric_parts(match_detail, f"胜场{wins}")
        lines.append(
            format_peak_line(
                title,
                current=f"当前{current_missing}" if current_missing else current,
                history=missing("history") or history,
                match_count=matches or 0 if match_missing is None else 0,
                win_rate=format_win_rate(wins, matches) if valid and matches else "",
                rank_result=rank,
                local_summary=local_summary,
                score_key=f"peak_{mode}",
                win_rate_key=f"peak_{mode}_win_rate",
                match_key=f"peak_{mode}_matches",
                invalid_counts=have_counts and not valid,
                match_detail=match_detail,
            )
        )
    if len(valid_totals) == len(rows):
        lines.append(f"巅峰总场次：{sum(valid_totals)}场")
    return "\n".join(lines)
