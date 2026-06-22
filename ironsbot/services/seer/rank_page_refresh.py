# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ironsbot.config import get_app_config
from ironsbot.services.seer.client import get_game_client
from ironsbot.services.seer.rank import fetch_daily_rank_page
from ironsbot.services.seer.rank_list import (
    GLOBAL_RANKS,
    GlobalRankSpec,
    batch_raw_start,
)
from ironsbot.services.seer.rank_page_cache import (
    CachedRankPageSummary,
    get_rank_page_cache_summary,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ironsbot.config.models.seer import RankPageRefreshConfig


REFRESH_REASON_MISSING = "缺失"
REFRESH_REASON_PARTIAL = "部分"
REFRESH_REASON_STALE = "过期"
REFRESH_REASONS = (
    REFRESH_REASON_MISSING,
    REFRESH_REASON_PARTIAL,
    REFRESH_REASON_STALE,
)


@dataclass(frozen=True, slots=True)
class RankPageRefreshTarget:
    rank_key: str
    spec: GlobalRankSpec
    reason: str
    start_rank: int
    end_rank: int
    raw_start: int
    raw_end: int


@dataclass(frozen=True, slots=True)
class RankPageRefreshFailure:
    target: RankPageRefreshTarget
    reason: str


@dataclass(slots=True)
class RankPageRefreshResult:
    targets: list[RankPageRefreshTarget]
    refreshed: list[RankPageRefreshTarget] = field(default_factory=list)
    failures: list[RankPageRefreshFailure] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.targets)

    @property
    def success(self) -> int:
        return len(self.refreshed)

    @property
    def failed(self) -> int:
        return len(self.failures)


def get_rank_page_refresh_config() -> RankPageRefreshConfig:
    return get_app_config().seer.rank.page_refresh


def configured_rank_specs(
    rank_keys: Sequence[str] | None = None,
) -> list[tuple[str, GlobalRankSpec]]:
    keys = (
        list(rank_keys)
        if rank_keys is not None
        else get_rank_page_refresh_config().rank_keys
    )
    specs: list[tuple[str, GlobalRankSpec]] = []
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            continue
        spec = GLOBAL_RANKS.get(key)
        if spec is None:
            continue
        seen.add(key)
        specs.append((key, spec))
    return specs


def page_refresh_rank_ranges(
    spec: GlobalRankSpec,
    *,
    target_limit: int,
    page_size: int,
) -> Iterable[tuple[int, int, int, int]]:
    for start_rank in range(1, target_limit + 1, page_size):
        end_rank = min(target_limit, start_rank + page_size - 1)
        raw_start = batch_raw_start(spec, start_rank)
        raw_end = raw_start + (end_rank - start_rank)
        yield start_rank, end_rank, raw_start, raw_end


def _is_page_stale(page: CachedRankPageSummary, *, stale_after_seconds: int) -> bool:
    if stale_after_seconds <= 0:
        return True
    return time.time() - page.fetched_at > stale_after_seconds


def _page_reason(
    page: CachedRankPageSummary | None,
    *,
    stale_after_seconds: int,
) -> str | None:
    if page is None:
        return REFRESH_REASON_MISSING
    if page.is_partial:
        return REFRESH_REASON_PARTIAL
    if _is_page_stale(page, stale_after_seconds=stale_after_seconds):
        return REFRESH_REASON_STALE
    return None


def _next_target_for_reason(  # noqa: PLR0913
    *,
    rank_key: str,
    spec: GlobalRankSpec,
    pages_by_range: dict[tuple[int, int], CachedRankPageSummary],
    reason: str,
    config: RankPageRefreshConfig,
    stale_after_seconds: int,
    selected_ranges: set[tuple[str, int, int]],
) -> RankPageRefreshTarget | None:
    for start_rank, end_rank, raw_start, raw_end in page_refresh_rank_ranges(
        spec,
        target_limit=config.target_limit,
        page_size=config.page_size,
    ):
        range_key = (rank_key, raw_start, raw_end)
        if range_key in selected_ranges:
            continue
        page = pages_by_range.get((raw_start, raw_end))
        if _page_reason(page, stale_after_seconds=stale_after_seconds) != reason:
            continue
        return RankPageRefreshTarget(
            rank_key=rank_key,
            spec=spec,
            reason=reason,
            start_rank=start_rank,
            end_rank=end_rank,
            raw_start=raw_start,
            raw_end=raw_end,
        )
    return None


def select_rank_page_refresh_targets(
    rank_specs: Sequence[tuple[str, GlobalRankSpec]],
    summaries: dict[str, Sequence[CachedRankPageSummary]],
    *,
    config: RankPageRefreshConfig | None = None,
) -> list[RankPageRefreshTarget]:
    refresh_config = config or get_rank_page_refresh_config()
    stale_after_seconds = refresh_config.refresh_stale_after_hours * 3600
    pages_by_rank = {
        rank_key: {
            (page.start_index, page.end_index): page
            for page in summaries.get(rank_key, ())
        }
        for rank_key, _spec in rank_specs
    }
    selected: list[RankPageRefreshTarget] = []
    selected_ranges: set[tuple[str, int, int]] = set()

    for reason in REFRESH_REASONS:
        while len(selected) < refresh_config.pages_per_run:
            added = False
            for rank_key, spec in rank_specs:
                target = _next_target_for_reason(
                    rank_key=rank_key,
                    spec=spec,
                    pages_by_range=pages_by_rank.get(rank_key, {}),
                    reason=reason,
                    config=refresh_config,
                    stale_after_seconds=stale_after_seconds,
                    selected_ranges=selected_ranges,
                )
                if target is None:
                    continue
                selected.append(target)
                selected_ranges.add((target.rank_key, target.raw_start, target.raw_end))
                added = True
                if len(selected) >= refresh_config.pages_per_run:
                    break
            if not added:
                break
    return selected


def preview_rank_page_refresh_targets(
    rank_keys: Sequence[str] | None = None,
) -> list[RankPageRefreshTarget]:
    rank_specs = configured_rank_specs(rank_keys)
    summaries = {
        rank_key: get_rank_page_cache_summary(key=spec.key, sub_key=spec.sub_key)
        for rank_key, spec in rank_specs
    }
    return select_rank_page_refresh_targets(rank_specs, summaries)


async def refresh_rank_page_cache(
    rank_keys: Sequence[str] | None = None,
) -> RankPageRefreshResult:
    targets = preview_rank_page_refresh_targets(rank_keys)
    result = RankPageRefreshResult(targets=targets)
    if not targets:
        return result

    game = get_game_client()
    for target in targets:
        try:
            await fetch_daily_rank_page(
                game,
                key=target.spec.key,
                sub_key=target.spec.sub_key,
                start=target.raw_start,
                count=target.raw_end - target.raw_start + 1,
                use_cache=False,
            )
        except Exception as e:  # noqa: BLE001
            result.failures.append(
                RankPageRefreshFailure(target=target, reason=str(e) or type(e).__name__)
            )
            continue
        result.refreshed.append(target)
    return result
