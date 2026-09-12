# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Iterable
from dataclasses import dataclass, field


class RankPageConflictError(ValueError):
    def __init__(self) -> None:
        super().__init__("榜单在查询期间发生变化，暂时无法确认排名。")


@dataclass(slots=True)
class RankPageSequence:
    """Validate distinct players and descending scores across ordered pages."""

    _players: set[int] = field(default_factory=set)
    _last_score: int | None = None

    def include(self, entries: Iterable[tuple[int, int]]) -> None:
        for user_id, score in entries:
            if user_id in self._players or (
                self._last_score is not None and score > self._last_score
            ):
                raise RankPageConflictError
            self._players.add(user_id)
            self._last_score = score


def rank_page_size(configured: int) -> int:
    return max(1, min(configured, 100))


def rank_page_start(index: int, *, page_size: int) -> int:
    return max(0, index) // page_size * page_size


def rank_window_page_starts(
    *,
    center_index: int,
    page_size: int,
    window_pages: int,
) -> list[int]:
    page_start = center_index // page_size * page_size
    starts = [page_start]
    for distance in range(1, window_pages + 1):
        previous = page_start - distance * page_size
        following = page_start + distance * page_size
        if previous >= 0:
            starts.append(previous)
        starts.append(following)
    return starts
