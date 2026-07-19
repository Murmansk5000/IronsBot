# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ironsbot.services.seer.formatting import format_datetime
from ironsbot.services.seer.rank_formatting import format_rank_position_text

if TYPE_CHECKING:
    from ironsbot.services.seer.local_rank_models import LocalRankSummary
    from ironsbot.services.seer.rank_models import RankLookupResult

METRIC_SEPARATOR = "\uff5c"
PEAK_RANK_NAMES = {
    0: "学徒",
    1: "猛将",
    2: "天骄",
    3: "王者",
    4: "圣皇",
    5: "宇宙圣皇",
}
COSMIC_SAINT_RANK_VALUE = 4
COSMIC_SAINT_MIN_STAR = 100


def filter_blank_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    for line in lines:
        if line == "" and (not result or result[-1] == ""):
            continue
        result.append(line)

    while result and result[-1] == "":
        result.pop()

    return result


def format_team_text(user_info: Any, team_name: str) -> str:
    team_id = getattr(user_info, "team_id", 0)
    if team_id <= 0:
        return "未加入"

    show_text = "展示" if getattr(user_info, "team_is_show", False) else "隐藏"
    return f"{team_name}（战队ID：{team_id}，{show_text}）"


def format_player_identity(
    player_id: int,
    nick: str | None = None,
) -> str:
    if nick:
        return f"米米号：{player_id}（{nick}）"
    return f"米米号：{player_id}"


def format_online_text(online_info: Any | None) -> str:
    if online_info is None:
        return "离线"

    return f"在线（服务器：{online_info.server_id}，地图类型：{online_info.map_type}）"


def format_login_timeline_lines(user_info: Any, online_info: Any | None) -> list[str]:
    events = [
        ("最后登录", int(getattr(user_info, "login_time", 0) or 0)),
        ("最后离线", int(getattr(user_info, "last_offline_time", 0) or 0)),
    ]
    ordered_events = sorted(
        enumerate(events),
        key=lambda item: (
            item[1][1] <= 0,
            item[1][1] if item[1][1] > 0 else item[0],
            item[0],
        ),
    )
    lines = [
        f"{label}：{format_datetime(timestamp)}"
        for _, (label, timestamp) in ordered_events
    ]
    lines.append(f"是否在线：{format_online_text(online_info)}")
    return lines


def format_vip(user_info: Any) -> str:
    if getattr(user_info, "vip", 0):
        return f"是（等级：{getattr(user_info, 'vip_level', 0)}）"
    return "否"


def format_rank_star_compact(rank: int, star: int) -> str:
    name = PEAK_RANK_NAMES.get(rank, f"段位{rank}")
    if rank == COSMIC_SAINT_RANK_VALUE and star >= COSMIC_SAINT_MIN_STAR:
        name = "宇宙圣皇"
    return f"{name}{star}星"


def format_win_rate(wins: int, total: int) -> str:
    if total <= 0:
        return "当前赛季未参赛"

    return f"{wins}/{total}={wins / total * 100:.3f}%"


def join_metric_parts(*parts: str) -> str:
    return METRIC_SEPARATOR.join(part for part in parts if part)


def sample_rank_text(summary: LocalRankSummary, key: str) -> str:
    return summary.sample_rank(key)


def format_metric_line(
    title: str,
    value: int | None,
    *,
    rank_result: RankLookupResult | None = None,
    local_summary: LocalRankSummary,
    local_key: str,
) -> str | None:
    value_text = str(value) if value is not None and value >= 0 else "暂无数据"

    metric_text = join_metric_parts(
        value_text,
        format_rank_position_text(rank_result),
        sample_rank_text(local_summary, local_key),
    )
    return f"{title}：{metric_text}"


def format_peak_rank_text(rank: int | None) -> str:
    return f"赛季榜第{rank}" if rank is not None else "赛季榜未上榜"


def format_local_rank_suffix(
    summary: LocalRankSummary,
    key: str,
    *,
    label: str = "样本",
) -> str:
    text = summary.sample_rank(key)
    if not text:
        return ""

    if text.startswith("样本"):
        text = f"{label}{text.removeprefix('样本')}"
    return f"（{text}）"
