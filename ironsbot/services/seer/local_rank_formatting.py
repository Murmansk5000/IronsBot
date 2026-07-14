# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

PERCENT_FINE_THRESHOLD = 10
_PEAK_RANK_NAMES = {
    0: "学徒",
    1: "猛将",
    2: "天骄",
    3: "王者",
    4: "圣皇",
    5: "宇宙圣皇",
}
_COSMIC_SAINT_RANK_VALUE = 4
_COSMIC_SAINT_MIN_STAR = 100


def format_percent(value: float) -> str:
    precision = 2 if value < PERCENT_FINE_THRESHOLD else 1
    return f"{value:.{precision}f}".rstrip("0").rstrip(".")


def format_peak_rating_score(value: int) -> str:
    rank, star = divmod(value, 100000)
    name = _PEAK_RANK_NAMES.get(rank, f"段位{rank}")
    if rank == _COSMIC_SAINT_RANK_VALUE and star >= _COSMIC_SAINT_MIN_STAR:
        name = "宇宙圣皇"
    return f"{name}{star}星"


def format_metric_display(
    metric_key: str,
    value: int,
    display: object | None = None,
) -> str:
    if display not in (None, ""):
        return str(display)
    if metric_key in {"peak_standard", "peak_wild"}:
        return format_peak_rating_score(value)
    if metric_key == "peak_expert":
        return f"{value}分"
    return str(value)
