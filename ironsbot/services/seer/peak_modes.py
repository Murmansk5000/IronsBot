# SPDX-License-Identifier: GPL-3.0-or-later
"""Verified game mode facts, independent of frontend tab numbers."""

from dataclasses import dataclass
from enum import Enum


class PeakType(Enum):
    STANDARD = 1
    WILD = 2
    EXPERT = 3
    MASTER = 4


@dataclass(frozen=True, slots=True)
class PeakMode:
    name: str
    slug: str
    website: str
    pet_keys: tuple[int, int, int]
    suit_keys: tuple[int, int]
    title_keys: tuple[int, int]
    personal_params: tuple[int, ...]
    master_season: bool = False


# Master facts were verified against the official GameLogic DLL, not inferred
# from adjacent keys. See docs/specs/master-peak-protocol.md.
PEAK_MODES = {
    PeakType.STANDARD: PeakMode(
        "竞技",
        "standard",
        "sports",
        (177, 93, 94),
        (173, 174),
        (175, 176),
        (124801, 124802, 124804, 124805),
    ),
    PeakType.WILD: PeakMode(
        "狂野",
        "wild",
        "wild",
        (185, 184, 183),
        (186, 187),
        (188, 189),
        (124791, 124792, 124793, 124794),
    ),
    PeakType.EXPERT: PeakMode(
        "专家",
        "expert",
        "expert",
        (202, 201, 200),
        (203, 204),
        (205, 206),
        (129441, 129443, 129446, 129447),
    ),
    PeakType.MASTER: PeakMode(
        "大师",
        "master",
        "master",
        (259, 258, 257),
        (260, 261),
        (262, 263),
        (408302, 408304, 408315),
        master_season=True,
    ),
}
PEAK_MODE_NAMES = frozenset(mode.slug for mode in PEAK_MODES.values())
PEAK_TYPE_NAME_MAP = {kind: mode.name for kind, mode in PEAK_MODES.items()}
PEAK_PET_KEY_MAP = {kind: mode.pet_keys for kind, mode in PEAK_MODES.items()}
PEAK_SUIT_KEY_MAP = {kind: mode.suit_keys for kind, mode in PEAK_MODES.items()}
PEAK_TITLE_KEY_MAP = {kind: mode.title_keys for kind, mode in PEAK_MODES.items()}


def combined_peak_season(regular: int | None, master: int | None) -> int | None:
    """Exact pair encoding fits SQLite int64 for eight-digit date subkeys."""
    if regular is None or master is None:
        return None
    return -(regular * 100_000_000 + master)
