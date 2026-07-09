# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ironsbot.services.seer.formatting import format_datetime
from ironsbot.services.seer.player_formatting_common import (
    filter_blank_lines,
    format_login_timeline_lines,
    format_team_text,
    format_vip,
)
from ironsbot.services.seer.player_peak_formatting import format_compact_peak_section

if TYPE_CHECKING:
    from ironsbot.services.seer.local_rank_models import LocalRankSummary
    from ironsbot.services.seer.rank_models import PeakSeasonRankSummary
    from ironsbot.services.seer.sequ_extra import UnityPeakInfo

def format_compact_player_info(  # noqa: PLR0913
    user_info: Any,
    more_info: Any,
    *,
    team_name: str,
    online_info: Any | None,
    unity_peak: UnityPeakInfo,
    peak_rank_summary: PeakSeasonRankSummary,
    local_summary: LocalRankSummary,
    has_collection: bool,
    has_peak: bool,
    has_autocard: bool,
    show_peak: bool,
    extra_errors: list[str],
) -> str:
    lines = [
        "🤖【玩家信息】",
        f"米米号：{user_info.user_id}（{user_info.nick}）",
        "",
        "【基础信息】",
        f"昵称：{user_info.nick}",
        f"VIP状态：{format_vip(user_info)}",
        f"注册时间：{format_datetime(getattr(more_info, 'reg_time', 0))}",
        *format_login_timeline_lines(user_info, online_info),
        "",
        f"战队：{format_team_text(user_info, team_name)}",
    ]

    if show_peak:
        lines.extend(
            (
                "",
                format_compact_peak_section(
                    unity_peak,
                    peak_rank_summary,
                    local_summary,
                ),
            )
        )

    if has_collection:
        lines.extend(("", "回复“收集”查看收集与排行"))

    if has_peak and not show_peak:
        lines.extend(("", "回复“巅峰”查看巅峰之战"))

    if has_autocard:
        lines.extend(("", "回复“群星牌”查看群星之巅排名"))

    if extra_errors:
        lines.extend(("", "【扩展数据提示】", "；".join(extra_errors)))

    return "\n".join(filter_blank_lines(lines))
