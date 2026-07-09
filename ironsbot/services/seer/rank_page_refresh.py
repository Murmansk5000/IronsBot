# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from math import log1p, sqrt
from typing import TYPE_CHECKING

from ironsbot.config.loader import get_app_config
from ironsbot.integrations.headless_seer.client import get_game_client
from ironsbot.services.seer.rank_list_formatting import batch_raw_start
from ironsbot.services.seer.rank_list_models import (
    GLOBAL_RANKS,
    GlobalRankSpec,
)
from ironsbot.services.seer.rank_page_cache_queries import (
    get_rank_page_cache_summary,
)
from ironsbot.services.seer.rank_pages import fetch_daily_rank_page

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from ironsbot.config.models.seer import RankPageRefreshConfig
    from ironsbot.services.seer.rank_page_cache_models import CachedRankPageSummary


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


@dataclass(frozen=True, slots=True)
class _RankPageRefreshCandidate:
    target: RankPageRefreshTarget
    score: float
    rank_order: int


def get_rank_page_refresh_config() -> RankPageRefreshConfig:
    return get_app_config().seer.rank.page_refresh


def rank_target_limit(config: RankPageRefreshConfig, rank_key: str) -> int:
    return config.target_limits.get(rank_key, config.target_limit)


def rank_score_cutoff(config: RankPageRefreshConfig, rank_key: str) -> int | None:
    return config.score_cutoffs.get(rank_key)


def rank_refresh_target_label(config: RankPageRefreshConfig, rank_key: str) -> str:
    target_limit = rank_target_limit(config, rank_key)
    score_cutoff = rank_score_cutoff(config, rank_key)
    if score_cutoff is not None:
        return f"分数 >= {score_cutoff}（最多前 {target_limit} 名）"
    return f"前 {target_limit} 名"


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


def _page_defect_ratio(
    page: CachedRankPageSummary | None,
    *,
    reason: str,
) -> float:
    if reason != REFRESH_REASON_PARTIAL or page is None:
        return 1.0
    expected_count = max(int(getattr(page, "expected_count", 0) or 0), 1)
    item_count = max(int(getattr(page, "item_count", 0) or 0), 0)
    return max(expected_count - item_count, 0) / expected_count


def _rank_position_score(*, end_rank: int, page_size: int) -> float:
    page_index = max((end_rank + page_size - 1) // page_size, 1)
    return 1 / sqrt(page_index)


def _stale_age_multiplier(
    config: RankPageRefreshConfig,
    page: CachedRankPageSummary | None,
    *,
    stale_after_seconds: int,
) -> float:
    if page is None or stale_after_seconds <= 0 or config.stale_age_weight <= 0:
        return 1.0
    age_seconds = max(time.time() - page.fetched_at, 0.0)
    if age_seconds <= stale_after_seconds:
        return 1.0
    overdue_hours = (age_seconds - stale_after_seconds) / 3600
    multiplier = 1.0 + log1p(overdue_hours) * config.stale_age_weight
    return min(multiplier, config.stale_age_max_multiplier)


def _rank_page_candidate_score(
    config: RankPageRefreshConfig,
    *,
    target: RankPageRefreshTarget,
    page: CachedRankPageSummary | None,
    stale_after_seconds: int,
) -> float:
    return (
        _rank_position_score(
            end_rank=target.end_rank,
            page_size=config.page_size,
        )
        * _page_defect_ratio(page, reason=target.reason)
        * _stale_age_multiplier(
            config,
            page,
            stale_after_seconds=stale_after_seconds,
        )
    )


def _page_reaches_score_cutoff(
    page: CachedRankPageSummary | None,
    *,
    score_cutoff: int | None,
) -> bool:
    if page is None or score_cutoff is None:
        return False
    min_score = getattr(page, "min_score", None)
    return min_score is not None and int(min_score) < score_cutoff


def _build_rank_page_candidates(  # noqa: PLR0913
    *,
    rank_key: str,
    spec: GlobalRankSpec,
    pages_by_range: dict[tuple[int, int], CachedRankPageSummary],
    config: RankPageRefreshConfig,
    target_limit: int,
    stale_after_seconds: int,
    rank_order: int,
) -> list[_RankPageRefreshCandidate]:
    candidates: list[_RankPageRefreshCandidate] = []
    score_cutoff = rank_score_cutoff(config, rank_key)
    for start_rank, end_rank, raw_start, raw_end in page_refresh_rank_ranges(
        spec,
        target_limit=target_limit,
        page_size=config.page_size,
    ):
        page = pages_by_range.get((raw_start, raw_end))
        reason = _page_reason(page, stale_after_seconds=stale_after_seconds)
        if reason is None:
            continue
        target = RankPageRefreshTarget(
            rank_key,
            spec,
            reason,
            start_rank,
            end_rank,
            raw_start,
            raw_end,
        )
        candidates.append(
            _RankPageRefreshCandidate(
                target=target,
                score=_rank_page_candidate_score(
                    config,
                    target=target,
                    page=page,
                    stale_after_seconds=stale_after_seconds,
                ),
                rank_order=rank_order,
            )
        )
        if _page_reaches_score_cutoff(page, score_cutoff=score_cutoff):
            break
    return candidates


def select_rank_page_refresh_targets(
    rank_specs: Sequence[tuple[str, GlobalRankSpec]],
    summaries: Mapping[str, Sequence[CachedRankPageSummary]],
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
    candidates: list[_RankPageRefreshCandidate] = []
    for rank_order, (rank_key, spec) in enumerate(rank_specs):
        candidates.extend(
            _build_rank_page_candidates(
                rank_key=rank_key,
                spec=spec,
                pages_by_range=pages_by_rank.get(rank_key, {}),
                config=refresh_config,
                target_limit=rank_target_limit(refresh_config, rank_key),
                stale_after_seconds=stale_after_seconds,
                rank_order=rank_order,
            )
        )
    candidates.sort(
        key=lambda candidate: (
            -candidate.score,
            candidate.target.start_rank,
            candidate.rank_order,
            candidate.target.raw_start,
        )
    )
    return [
        candidate.target
        for candidate in candidates[: refresh_config.pages_per_run]
    ]


def filter_standard_rank_page_summaries(
    spec: GlobalRankSpec,
    pages: Sequence[CachedRankPageSummary],
    *,
    rank_key: str | None = None,
    config: RankPageRefreshConfig | None = None,
) -> list[CachedRankPageSummary]:
    """Keep scheduled refresh pages for coverage stats.

    Player lookups may cache narrow probe ranges such as 1-1 or 24-24. Those
    fragments are still useful for future rank lookup, but including them in
    coverage/status output makes the progress look broken.
    """
    refresh_config = config or get_rank_page_refresh_config()
    standard_ranges = {
        (raw_start, raw_end)
        for _start_rank, _end_rank, raw_start, raw_end in page_refresh_rank_ranges(
            spec,
            target_limit=(
                rank_target_limit(refresh_config, rank_key)
                if rank_key is not None
                else refresh_config.target_limit
            ),
            page_size=refresh_config.page_size,
        )
    }
    filtered = [
        page
        for page in pages
        if (page.start_index, page.end_index) in standard_ranges
    ]
    score_cutoff = (
        rank_score_cutoff(refresh_config, rank_key)
        if rank_key is not None
        else None
    )
    if score_cutoff is None:
        return filtered

    result: list[CachedRankPageSummary] = []
    for page in sorted(filtered, key=lambda item: (item.start_index, item.end_index)):
        result.append(page)
        if _page_reaches_score_cutoff(page, score_cutoff=score_cutoff):
            break
    return result


def preview_rank_page_refresh_targets(
    rank_keys: Sequence[str] | None = None,
) -> list[RankPageRefreshTarget]:
    rank_specs = configured_rank_specs(rank_keys)
    summaries = {
        rank_key: get_rank_page_cache_summary(key=spec.key, sub_key=spec.sub_key)
        for rank_key, spec in rank_specs
    }
    return select_rank_page_refresh_targets(rank_specs, summaries)


async def _sleep_between_rank_page_requests(config: RankPageRefreshConfig) -> None:
    delay = config.request_interval_seconds
    if config.request_jitter_seconds > 0:
        delay += random.uniform(0, config.request_jitter_seconds)  # nosec B311
    if delay > 0:
        await asyncio.sleep(delay)


async def refresh_rank_page_cache(
    rank_keys: Sequence[str] | None = None,
) -> RankPageRefreshResult:
    refresh_config = get_rank_page_refresh_config()
    targets = preview_rank_page_refresh_targets(rank_keys)
    if refresh_config.pages_per_run_min > 0 and targets:
        lower = min(refresh_config.pages_per_run_min, len(targets))
        upper = min(refresh_config.pages_per_run, len(targets))
        target_count = random.randint(  # nosec B311
            lower,
            upper,
        )
        targets = targets[:target_count]
    result = RankPageRefreshResult(targets=targets)
    if not targets:
        return result

    game = get_game_client()
    for index, target in enumerate(targets):
        if index > 0:
            await _sleep_between_rank_page_requests(refresh_config)
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
