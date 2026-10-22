# SPDX-License-Identifier: GPL-3.0-or-later
"""Cache-only equivalents of the public rank numbering policies."""

from __future__ import annotations

from typing import Any

from ironsbot.core.time import ObservationTime
from ironsbot.services.seer.rank_models import RankRangeResult
from ironsbot.services.seer.rank_pagination import (
    RankPageConflictError,
    RankPageSequence,
)
from ironsbot.services.seer.rank_visibility import (
    EXCLUSION_PREFIX_SIZE,
    RankVisibility,
    uses_filtered_prefix,
)


class CachedRankVisibility:
    def __init__(
        self, host: Any, *, rank_key: str | None, key: int, sub_key: int
    ) -> None:
        self.host = host
        self.rank_key, self.key, self.sub_key = rank_key, key, sub_key
        self.pages: dict[int, Any] = {}
        self.prefix: list[Any] = []
        self.observation = ObservationTime()

    def page(self, start: int) -> Any | None:
        if start not in self.pages:
            page = self.host.cache.page(
                key=self.key,
                sub_key=self.sub_key,
                start=start,
                end=start + self.host.page_size() - 1,
                allow_stale=False,
            )
            if page is None:
                return None
            self.pages[start] = page
            self.observation.include(page.fetched_at)
        return self.pages[start]

    def visibility(
        self, *, public_until: int | None = None, raw_until: int | None = None
    ) -> RankVisibility | None:
        ids = (
            self.host.exclusion_policy.excluded_user_ids(self.rank_key)
            if self.rank_key is not None
            else frozenset()
        )
        prefix: list[Any] = []
        if uses_filtered_prefix(self.rank_key) and ids:
            sequence = RankPageSequence()
            limit = (
                min(EXCLUSION_PREFIX_SIZE, raw_until)
                if raw_until is not None
                else EXCLUSION_PREFIX_SIZE
            )
            visible_count = 0
            for start in range(0, limit, self.host.page_size()):
                page = self.page(start)
                if page is None:
                    return None
                items = page.items[: EXCLUSION_PREFIX_SIZE - start]
                try:
                    sequence.include((int(item.id), int(item.score)) for item in items)
                except RankPageConflictError:
                    return None
                prefix.extend(items)
                visible_count += sum(int(item.id) not in ids for item in items)
                if public_until is not None and visible_count >= public_until:
                    break
                if len(page.items) < self.host.page_size():
                    break
        self.prefix = prefix
        return RankVisibility.build(self.rank_key, ids, prefix)

    def range(
        self, start_rank: int, count: int, *, ascending: bool
    ) -> RankRangeResult | None:
        if count <= 0:
            return RankRangeResult([], None, from_cache=True, ranks=[])
        visibility = self.visibility(public_until=max(0, start_rank - 1) + count)
        if visibility is None:
            return None
        first = visibility.raw_index(max(0, start_rank - 1))
        last = visibility.raw_index(max(0, start_rank - 1) + count - 1)
        size = self.host.page_size()
        sequence = RankPageSequence(ascending=ascending)
        rows: list[tuple[int, Any]] = []
        for start in range(first // size * size, last + 1, size):
            page = self.page(start)
            if page is None:
                return None
            try:
                sequence.include((int(item.id), int(item.score)) for item in page.items)
            except RankPageConflictError:
                return None
            rows.extend(
                (visibility.public_index(start + offset) + 1, item)
                for offset, item in enumerate(page.items)
                if first <= start + offset <= last
                and not visibility.hides(start + offset, int(item.id))
            )
            if len(page.items) < size:
                break
        if self.prefix:
            sequence = RankPageSequence(ascending=ascending)
            try:
                sequence.include(
                    (int(item.id), int(item.score)) for item in self.prefix
                )
                sequence.include(
                    (int(item.id), int(item.score))
                    for rank, item in rows
                    if visibility.raw_index(rank - 1) >= len(self.prefix)
                )
            except RankPageConflictError:
                return None
        return RankRangeResult(
            [item for _, item in rows],
            self.observation.fetched_at,
            from_cache=True,
            ranks=[rank for rank, _ in rows],
        )
