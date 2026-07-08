# SPDX-License-Identifier: GPL-3.0-or-later
from dataclasses import dataclass
from enum import Enum


@dataclass(slots=True)
class PeakData:
    current_score: int
    current_highest_score: int
    history_highest_score: int


@dataclass(slots=True)
class PeakItemData:
    id: int
    count: int
    win: int
    ban_count: int | None = None

    @property
    def win_rate(self) -> float:
        if self.count == 0:
            return 0
        return round(self.win / self.count * 100, 2)


class PeakType(Enum):
    STANDARD = 1
    WILD = 2
    EXPERT = 3


PEAK_TYPE_NAME_MAP = {
    PeakType.STANDARD: "竞技",
    PeakType.WILD: "狂野",
    PeakType.EXPERT: "专家",
}

PEAK_PET_KEY_MAP = {
    PeakType.STANDARD: (177, 93, 94),
    PeakType.WILD: (185, 184, 183),
    PeakType.EXPERT: (202, 201, 200),
}

PEAK_SUIT_KEY_MAP = {
    PeakType.STANDARD: (173, 174),
    PeakType.WILD: (186, 187),
    PeakType.EXPERT: (203, 204),
}

PEAK_TITLE_KEY_MAP = {
    PeakType.STANDARD: (175, 176),
    PeakType.WILD: (188, 189),
    PeakType.EXPERT: (205, 206),
}

PEAK_USER_KEY_MAP = {
    PeakType.STANDARD: 120,
    PeakType.WILD: 182,
    PeakType.EXPERT: 199,
}


__all__ = [
    "PEAK_PET_KEY_MAP",
    "PEAK_SUIT_KEY_MAP",
    "PEAK_TITLE_KEY_MAP",
    "PEAK_TYPE_NAME_MAP",
    "PEAK_USER_KEY_MAP",
    "PeakData",
    "PeakItemData",
    "PeakType",
]

