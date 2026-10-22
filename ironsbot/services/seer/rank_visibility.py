# SPDX-License-Identifier: GPL-3.0-or-later
"""Translate raw server positions without scanning beyond the exclusion prefix."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.services.seer.rank_list_models import GLOBAL_RANKS
from ironsbot.services.seer.rank_models import RankScoreSearchItem

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from typing import Any

    from ironsbot.services.seer.rank_models import RankScoreSearchResult

EXCLUSION_PREFIX_SIZE = 1000


def uses_filtered_prefix(rank_key: str | None) -> bool:
    spec = GLOBAL_RANKS.get(rank_key) if rank_key is not None else None
    return spec is not None and spec.numbering == "filtered_prefix"


@dataclass(frozen=True, slots=True)
class RankVisibility:
    excluded_ids: frozenset[int]
    filtered_prefix: bool
    hidden_indexes: tuple[int, ...] = ()

    @classmethod
    def build(
        cls,
        rank_key: str | None,
        excluded_ids: Collection[int],
        prefix: Sequence[Any] = (),
    ) -> RankVisibility:
        filtered = uses_filtered_prefix(rank_key)
        hidden = (
            tuple(
                index
                for index, item in enumerate(prefix[:EXCLUSION_PREFIX_SIZE])
                if int(item.id) in excluded_ids
            )
            if filtered
            else ()
        )
        return cls(frozenset(excluded_ids), filtered, hidden)

    def hides(self, raw_index: int, user_id: int) -> bool:
        return user_id in self.excluded_ids and (
            not self.filtered_prefix or raw_index < EXCLUSION_PREFIX_SIZE
        )

    def public_index(self, raw_index: int) -> int:
        return raw_index - bisect_left(self.hidden_indexes, raw_index)

    def raw_index(self, public_index: int) -> int:
        raw = public_index
        for hidden in self.hidden_indexes:
            if hidden > raw:
                break
            raw += 1
        return raw

    def visible_bounds(self, first: int, last: int) -> tuple[int, int, int]:
        """Return bounds/count for a raw inclusive segment, without sampling bias."""
        hidden = set(self.hidden_indexes)
        count = (
            last
            - first
            + 1
            - (
                bisect_right(self.hidden_indexes, last)
                - bisect_left(self.hidden_indexes, first)
            )
        )
        while first <= last and first in hidden:
            first += 1
        while last >= first and last in hidden:
            last -= 1
        return self.public_index(first), self.public_index(last), max(0, count)

    def apply_score_result(
        self, result: RankScoreSearchResult
    ) -> RankScoreSearchResult:
        def convert(items: list[Any]) -> list[Any]:
            return [
                RankScoreSearchItem(
                    item.id, item.nick, item.score, self.public_index(item.rank_index)
                )
                for item in items
                if not self.hides(item.rank_index, item.id)
            ]

        original_items = result.items
        result.items = convert(original_items)
        result.scanned_count = len(result.items)
        if result.start_rank is not None and result.end_rank is not None:
            first, last, count = self.score_bounds(
                result.start_rank - 1,
                result.end_rank - 1,
                original_items,
                result.total_count,
            )
            if self.excluded_ids and result.truncated:
                count = len(result.items)
                if result.items:
                    first, last = (
                        result.items[0].rank_index,
                        result.items[-1].rank_index,
                    )
            result.start_rank = first + 1 if count else None
            result.end_rank = last + 1 if count else None
            result.total_count = count
        for gap in (result.higher_gap, result.lower_gap):
            if gap is None:
                continue
            originals = gap.items
            first, last, count = self.score_bounds(
                gap.start_rank - 1, gap.end_rank - 1, originals, gap.total_count
            )
            gap.items = convert(originals)
            gap.total_count = count
            gap.start_rank, gap.end_rank = first + 1, last + 1
            if gap.total_count == 0:
                if gap is result.higher_gap:
                    result.higher_gap = None
                else:
                    result.lower_gap = None
        return result

    def score_bounds(
        self, first: int, last: int, items: list[RankScoreSearchItem], total: int
    ) -> tuple[int, int, int]:
        if self.filtered_prefix:
            return self.visible_bounds(first, last)
        hidden = {
            item.rank_index for item in items if self.hides(item.rank_index, item.id)
        }
        count = total - len(hidden)
        while first <= last and first in hidden:
            first += 1
        while last >= first and last in hidden:
            last -= 1
        return first, last, count
