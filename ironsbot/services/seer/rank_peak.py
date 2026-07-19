# SPDX-License-Identifier: GPL-3.0-or-later
import re
from datetime import datetime

PEAK_RATING_VALUES = {
    "学徒": 0,
    "猛将": 1,
    "天骄": 2,
    "王者": 3,
    "圣皇": 4,
}

COSMIC_SAINT_RANK_NAME = "宇宙圣皇"
COSMIC_SAINT_RANK_VALUE = 4
COSMIC_SAINT_MIN_STAR = 100


def datetime_to_sub_key(value: datetime) -> int:
    return int(value.strftime("%Y%m%d"))


def build_peak_rating_score(rank: int, star: int) -> int | None:
    if rank <= 0 and star <= 0:
        return None
    return rank * 100000 + star


def _parse_peak_star_text(star_text: str) -> int | None:
    if not star_text:
        return 0

    match = re.fullmatch(r"(\d+)(?:星|分)?", star_text)
    if match is None:
        return None
    return int(match.group(1))


def parse_peak_rating_score_text(text: str) -> int | None:
    normalized = "".join(text.split())
    if normalized.startswith(COSMIC_SAINT_RANK_NAME):
        star = _parse_peak_star_text(normalized[len(COSMIC_SAINT_RANK_NAME) :])
        if star is None or star < COSMIC_SAINT_MIN_STAR:
            return None
        return build_peak_rating_score(COSMIC_SAINT_RANK_VALUE, star)

    for name, rank in sorted(
        PEAK_RATING_VALUES.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if not normalized.startswith(name):
            continue

        star_text = normalized[len(name) :]
        star = _parse_peak_star_text(star_text)
        if star is None:
            return None
        return build_peak_rating_score(rank, star)

    return None
