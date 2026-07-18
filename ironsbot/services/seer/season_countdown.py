# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from ironsbot.config.models.seer import SeasonCountdownConfig

CHINA_TZ = timezone(timedelta(hours=8))


@dataclass(slots=True)
class SeasonWindow:
    name: str
    start_time: datetime | None
    end_time: datetime | None


def _as_china_time(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=CHINA_TZ)
    return value.astimezone(CHINA_TZ)


def _format_time(value: datetime | None) -> str:
    china_time = _as_china_time(value)
    if china_time is None:
        return "未知"
    return china_time.strftime("%Y-%m-%d %H:%M")


def _format_duration(delta: timedelta) -> str:
    total_seconds = max(0, int(delta.total_seconds()))
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _seconds = divmod(remainder, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}天")
    if hours or days:
        parts.append(f"{hours}小时")
    parts.append(f"{minutes}分钟")
    return "".join(parts)


def _format_window(window: SeasonWindow, *, now: datetime) -> str:
    start = _as_china_time(window.start_time)
    end = _as_china_time(window.end_time)

    if end is None:
        return f"{window.name}：未收录赛季结束时间"

    period = f"{_format_time(start)} ~ {_format_time(end)}"
    if start is not None and now < start:
        return (
            f"{window.name}：{period}\n"
            f"状态：未开始，距离开始 {_format_duration(start - now)}"
        )
    if now < end:
        return (
            f"{window.name}：{period}\n"
            f"状态：进行中，剩余 {_format_duration(end - now)}"
        )
    return (
        f"{window.name}：{period}\n"
        f"状态：已结束，结束于 {_format_duration(now - end)}前"
    )


def load_peak_season_window(session: Any) -> SeasonWindow | None:
    try:
        from seerapi_models import PeakSeasonORM
    except ImportError:
        return None

    season = session.get(PeakSeasonORM, 1)
    if season is None:
        return None
    return SeasonWindow(
        name="巅峰圣战赛季",
        start_time=cast("datetime | None", season.start_time),
        end_time=cast("datetime | None", season.end_time),
    )


def load_autocard_season_window(
    config: SeasonCountdownConfig,
) -> SeasonWindow:
    return SeasonWindow(
        name=config.autocard_name,
        start_time=cast("datetime | None", config.autocard_start_time),
        end_time=cast("datetime | None", config.autocard_end_time),
    )


def format_season_countdown(
    session: Any,
    config: SeasonCountdownConfig,
) -> str:
    now = _as_china_time(datetime.now(CHINA_TZ))
    if now is None:
        now = datetime.now(CHINA_TZ)
    lines = [
        "⏳【赛季倒计时】",
        f"截至：{now.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    peak = load_peak_season_window(session)
    if peak is None:
        lines.append("巅峰圣战赛季：未找到赛季数据")
    else:
        lines.append(_format_window(peak, now=now))

    lines.extend(("", _format_window(load_autocard_season_window(config), now=now)))
    return "\n".join(lines)


__all__ = [
    "SeasonWindow",
    "format_season_countdown",
    "load_autocard_season_window",
    "load_peak_season_window",
]
