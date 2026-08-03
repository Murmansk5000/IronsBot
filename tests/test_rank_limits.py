import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

import nonebot
from pytest import MonkeyPatch

ONLINE_LIMIT = 2000
RANK_LIMIT = 10000
CACHED_RANK = 50000
CACHED_RANK_INDEX = CACHED_RANK - 1
CACHED_SCORE = 12345
LOW_TARGET_SCORE = 99
BINARY_ONLINE_LIMIT = 1000
BINARY_TARGET_INDEX = 250
BINARY_TARGET_RANK = BINARY_TARGET_INDEX + 1
BINARY_TARGET_SCORE = RANK_LIMIT - BINARY_TARGET_INDEX
DEFAULT_PROBE_LIMIT = 32
TIED_PAGE_SIZE = 10
TIED_PAGE_LIMIT = 3
TIED_PROBE_LIMIT = 12
TIED_SCORE = 100
SEGMENT_SCORE = 150
SEGMENT_START_INDEX = 20
SEGMENT_END_INDEX = 45
SEGMENT_START_RANK = SEGMENT_START_INDEX + 1
SEGMENT_COUNT = SEGMENT_END_INDEX - SEGMENT_START_INDEX
SEGMENT_BOUNDARY_SCORE = 100
CACHED_HINT_SEGMENT_START_INDEX = 23
CACHED_HINT_SEGMENT_END_INDEX = 43
CACHED_HINT_SEGMENT_START_RANK = CACHED_HINT_SEGMENT_START_INDEX + 1
CACHED_HINT_SEGMENT_COUNT = (
    CACHED_HINT_SEGMENT_END_INDEX - CACHED_HINT_SEGMENT_START_INDEX
)
REFRESHED_CANDIDATE_RANK = 59
ONLINE_GAP_UPPER_SCORE = 200
ONLINE_GAP_UPPER_START_RANK = 11
ONLINE_GAP_UPPER_END_RANK = 20
ONLINE_GAP_LOWER_START_RANK = 21
ONLINE_GAP_LOWER_END_RANK = 30
FETCHED_AT = 1_781_234_567.0
LOOKUP_INDEX = 14
MOVED_RANK = 150
LARGE_SEGMENT_LIMIT = 50_000
LARGE_SEGMENT_PROBE_LIMIT = 16
LARGE_SEGMENT_PAGE_SIZE = 100
LARGE_SEGMENT_START_INDEX = 856
LARGE_SEGMENT_END_INDEX = 1156
LARGE_SEGMENT_SAMPLE_LIMIT = 50

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()
try:
    nonebot.load_plugin("nonebot_plugin_htmlkit")
except RuntimeError as e:
    if "Plugin already exists" not in str(e):
        raise

from ironsbot.config.models.seer import RankQueryConfig
from ironsbot.integrations.headless_seer.rank import fetch_rank_page
from ironsbot.services.seer.rank import RankPageCache, RankService
from ironsbot.services.seer.rank_models import RankPageResult
from ironsbot.services.seer.rank_page_cache_models import (
    CachedRankLookup,
)

if TYPE_CHECKING:
    from ironsbot.integrations.headless_seer.game import SeerGame

GAME = cast("SeerGame", object())


@dataclass(frozen=True)
class LocalRankConfig:
    refresh_interval_seconds: int


@dataclass(frozen=True)
class RankItem:
    score: int
    id: int = 0
    nick: str = ""


@dataclass(frozen=True)
class RankPageSummary:
    start_index: int
    end_index: int
    min_score: int
    max_score: int
    item_count: int = 0
    expected_count: int = 0
    fetched_at: float = 0.0
    is_stale: bool = False
    is_partial: bool = False


@dataclass(frozen=True)
class RankListResponse:
    rank_list: list[RankItem]


class RankRequestParam(Protocol):
    start: int
    end: int


class FakeRankPageCache:
    def page(self, **_kwargs: object) -> object | None:
        return None

    def item(self, **_kwargs: object) -> object | None:
        return None

    def item_by_index(self, **_kwargs: object) -> object | None:
        return None

    def summary(self, **_kwargs: object) -> list[object]:
        return []

    def score_indexes(self, **_kwargs: object) -> list[int]:
        return []

    def save(self, **_kwargs: object) -> None:
        return


def _build_rank(
    *,
    online_limit: int = ONLINE_LIMIT,
    rank_limit: int = RANK_LIMIT,
    page_size: int = 100,
    score_search_probe_limit: int = 32,
    score_search_tie_page_limit: int = 5,
) -> tuple[RankService, FakeRankPageCache]:
    config = RankQueryConfig(
        limit=rank_limit,
        online_limit=online_limit,
        page_size=page_size,
        score_search_probe_limit=score_search_probe_limit,
        score_search_tie_page_limit=score_search_tie_page_limit,
    )
    cache = FakeRankPageCache()
    return (
        RankService(
            config,
            cast("RankPageCache", cache),
            lambda: None,
            fetch_rank_page,
        ),
        cache,
    )


def test_score_rank_lookup_uses_rank_limit_not_online_limit(
    monkeypatch: MonkeyPatch,
) -> None:
    rank, cache = _build_rank(online_limit=ONLINE_LIMIT)
    requested_indexes: list[int] = []

    monkeypatch.setattr(cache, "item", lambda **_: None)

    async def fake_fetch_rank_item(
        *_args: object,
        index: int,
        **_kwargs: object,
    ) -> RankItem:
        requested_indexes.append(index)
        return RankItem(score=0)

    monkeypatch.setattr(RankService, "fetch_item", fake_fetch_rank_item)

    result = asyncio.run(
        rank.find_rank(
            GAME,
            user_id=712345678,
            title="achievement",
            score_name="score",
            key=17,
            sub_key=0,
            target_score=100,
        )
    )

    assert result.searched_limit == RANK_LIMIT
    assert requested_indexes
    assert max(requested_indexes) == RANK_LIMIT - 1
    assert max(requested_indexes) >= ONLINE_LIMIT


def test_rank_lookup_without_score_uses_online_limit_for_linear_scan(
    monkeypatch: MonkeyPatch,
) -> None:
    online_limit = 250
    page_size = 100
    rank, cache = _build_rank(online_limit=online_limit, page_size=page_size)
    requested_pages: list[tuple[int, int]] = []

    monkeypatch.setattr(cache, "item", lambda **_: None)

    async def fake_fetch_rank_page(
        *_args: object,
        start: int,
        end: int,
        **_kwargs: object,
    ) -> list[RankItem]:
        requested_pages.append((start, end))
        return [
            RankItem(id=rank_index, score=online_limit - rank_index)
            for rank_index in range(start, end + 1)
        ]

    monkeypatch.setattr(RankService, "fetch_page", fake_fetch_rank_page)

    result = asyncio.run(
        rank.find_rank(
            GAME,
            user_id=712345678,
            title="autocard",
            score_name="score",
            key=240,
            sub_key=1,
        )
    )

    assert result.rank is None
    assert result.searched_limit == online_limit
    assert requested_pages == [(0, 99), (100, 199), (200, 249)]


def test_score_rank_lookup_rejects_target_below_boundary(
    monkeypatch: MonkeyPatch,
) -> None:
    rank, cache = _build_rank(online_limit=ONLINE_LIMIT)
    requested_indexes: list[int] = []

    monkeypatch.setattr(cache, "item", lambda **_: None)

    async def fake_fetch_rank_item(
        *_args: object,
        index: int,
        **_kwargs: object,
    ) -> RankItem:
        requested_indexes.append(index)
        return RankItem(score=100)

    monkeypatch.setattr(RankService, "fetch_item", fake_fetch_rank_item)

    result = asyncio.run(
        rank.find_rank(
            GAME,
            user_id=712345678,
            title="achievement",
            score_name="score",
            key=17,
            sub_key=0,
            target_score=LOW_TARGET_SCORE,
        )
    )

    assert result.rank is None
    assert result.score == LOW_TARGET_SCORE
    assert requested_indexes == [RANK_LIMIT - 1]


def test_score_rank_lookup_finds_rank_with_binary_search(
    monkeypatch: MonkeyPatch,
) -> None:
    rank, cache = _build_rank(online_limit=BINARY_ONLINE_LIMIT)
    requested_indexes: list[int] = []
    requested_pages: list[tuple[int, int]] = []

    monkeypatch.setattr(cache, "item", lambda **_: None)

    async def fake_fetch_rank_item(
        *_args: object,
        index: int,
        **_kwargs: object,
    ) -> RankItem:
        requested_indexes.append(index)
        return RankItem(score=RANK_LIMIT - index)

    async def fake_fetch_rank_page(
        *_args: object,
        start: int,
        end: int,
        **_kwargs: object,
    ) -> list[RankItem]:
        requested_pages.append((start, end))
        return [
            RankItem(
                id=712345678 if rank_index == BINARY_TARGET_INDEX else rank_index,
                score=RANK_LIMIT - rank_index,
            )
            for rank_index in range(start, end + 1)
        ]

    monkeypatch.setattr(RankService, "fetch_item", fake_fetch_rank_item)
    monkeypatch.setattr(RankService, "fetch_page", fake_fetch_rank_page)

    result = asyncio.run(
        rank.find_rank(
            GAME,
            user_id=712345678,
            title="achievement",
            score_name="score",
            key=17,
            sub_key=0,
            target_score=BINARY_TARGET_SCORE,
        )
    )

    assert result.rank == BINARY_TARGET_RANK
    assert result.score == BINARY_TARGET_SCORE
    assert max(requested_indexes) == RANK_LIMIT - 1
    assert len(requested_indexes) <= DEFAULT_PROBE_LIMIT
    assert requested_pages == [
        (BINARY_TARGET_INDEX, BINARY_TARGET_INDEX),
        (0, 99),
        (100, 199),
        (200, 299),
    ]


def test_score_rank_lookup_limits_tied_score_page_scan(
    monkeypatch: MonkeyPatch,
) -> None:
    rank, cache = _build_rank(
        online_limit=BINARY_ONLINE_LIMIT,
        rank_limit=BINARY_ONLINE_LIMIT,
        page_size=TIED_PAGE_SIZE,
        score_search_probe_limit=TIED_PROBE_LIMIT,
        score_search_tie_page_limit=TIED_PAGE_LIMIT,
    )
    requested_pages: list[tuple[int, int]] = []

    monkeypatch.setattr(cache, "item", lambda **_: None)

    async def fake_fetch_rank_item(
        *_args: object,
        index: int,  # noqa: ARG001
        **_kwargs: object,
    ) -> RankItem:
        return RankItem(score=TIED_SCORE)

    async def fake_fetch_rank_page(
        *_args: object,
        start: int,
        end: int,
        **_kwargs: object,
    ) -> list[RankItem]:
        requested_pages.append((start, end))
        return [
            RankItem(id=rank_index, score=TIED_SCORE)
            for rank_index in range(start, end + 1)
        ]

    monkeypatch.setattr(RankService, "fetch_item", fake_fetch_rank_item)
    monkeypatch.setattr(RankService, "fetch_page", fake_fetch_rank_page)

    result = asyncio.run(
        rank.find_rank(
            GAME,
            user_id=712345678,
            title="achievement",
            score_name="score",
            key=17,
            sub_key=0,
            target_score=TIED_SCORE,
        )
    )

    assert result.rank is None
    assert requested_pages == [
        (0, TIED_PAGE_SIZE - 1),
        (TIED_PAGE_SIZE, TIED_PAGE_SIZE * 2 - 1),
        (TIED_PAGE_SIZE * 2, TIED_PAGE_SIZE * TIED_PAGE_LIMIT - 1),
    ]


def test_fetch_rank_score_segment_uses_binary_search_and_fetches_tie_pages(
    monkeypatch: MonkeyPatch,
) -> None:
    rank, _cache = _build_rank(
        online_limit=100,
        rank_limit=100,
        page_size=TIED_PAGE_SIZE,
        score_search_probe_limit=20,
        score_search_tie_page_limit=5,
    )
    requested_pages: list[tuple[int, int]] = []
    probe_use_cache_values: list[bool] = []
    page_use_cache_values: list[bool] = []

    async def fake_fetch_rank_item(
        *_args: object,
        index: int,
        use_cache: bool = True,
        **_kwargs: object,
    ) -> RankItem:
        probe_use_cache_values.append(use_cache)
        if index < SEGMENT_START_INDEX:
            score = 200
        elif index < SEGMENT_END_INDEX:
            score = SEGMENT_SCORE
        else:
            score = SEGMENT_BOUNDARY_SCORE
        return RankItem(id=index, nick=f"Player{index}", score=score)

    async def fake_fetch_rank_page_result(
        *_args: object,
        start: int,
        end: int,
        use_cache: bool = True,
        **_kwargs: object,
    ) -> RankPageResult:
        requested_pages.append((start, end))
        page_use_cache_values.append(use_cache)
        items = []
        for rank_index in range(start, end + 1):
            if rank_index < SEGMENT_START_INDEX:
                score = 200
            elif rank_index < SEGMENT_END_INDEX:
                score = SEGMENT_SCORE
            else:
                score = SEGMENT_BOUNDARY_SCORE
            items.append(
                RankItem(
                    id=rank_index,
                    nick=f"Player{rank_index}",
                    score=score,
                )
            )
        return RankPageResult(items=items, fetched_at=FETCHED_AT)

    monkeypatch.setattr(RankService, "fetch_item", fake_fetch_rank_item)
    monkeypatch.setattr(
        RankService,
        "fetch_page_result",
        fake_fetch_rank_page_result,
    )

    result = asyncio.run(
        rank.fetch_score_segment(
            GAME,
            title="achievement",
            score_name="score",
            key=17,
            sub_key=0,
            target_score=SEGMENT_SCORE,
        )
    )

    assert result.start_rank == SEGMENT_START_RANK
    assert result.end_rank == SEGMENT_END_INDEX
    assert result.total_count == SEGMENT_COUNT
    assert result.scanned_count == SEGMENT_COUNT
    assert [item.id for item in result.items] == list(
        range(SEGMENT_START_INDEX, SEGMENT_END_INDEX)
    )
    assert probe_use_cache_values
    assert all(use_cache is False for use_cache in probe_use_cache_values)
    assert page_use_cache_values == [False, False, False]
    assert requested_pages == [(20, 29), (30, 39), (40, 49)]


def test_fetch_rank_score_segment_samples_only_tie_range_head_and_tail(
    monkeypatch: MonkeyPatch,
) -> None:
    segment_start = 10
    segment_end = 90
    sample_limit = 10
    rank, _cache = _build_rank(
        online_limit=100,
        rank_limit=100,
        page_size=TIED_PAGE_SIZE,
        score_search_probe_limit=20,
        score_search_tie_page_limit=5,
    )
    requested_pages: list[tuple[int, int]] = []

    def score_at(index: int) -> int:
        if index < segment_start:
            return 200
        if index < segment_end:
            return SEGMENT_SCORE
        return SEGMENT_BOUNDARY_SCORE

    async def fake_fetch_rank_item(
        *_args: object,
        index: int,
        **_kwargs: object,
    ) -> RankItem:
        return RankItem(id=index, nick=f"Player{index}", score=score_at(index))

    async def fake_fetch_rank_page_result(
        *_args: object,
        start: int,
        end: int,
        **_kwargs: object,
    ) -> RankPageResult:
        requested_pages.append((start, end))
        return RankPageResult(
            items=[
                RankItem(
                    id=index,
                    nick=f"Player{index}",
                    score=score_at(index),
                )
                for index in range(start, end + 1)
            ],
            fetched_at=FETCHED_AT,
        )

    monkeypatch.setattr(RankService, "fetch_item", fake_fetch_rank_item)
    monkeypatch.setattr(
        RankService,
        "fetch_page_result",
        fake_fetch_rank_page_result,
    )

    result = asyncio.run(
        rank.fetch_score_segment(
            GAME,
            title="standard peak",
            score_name="score",
            key=17,
            sub_key=0,
            target_score=SEGMENT_SCORE,
            sample_limit=sample_limit,
        )
    )

    assert result.start_rank == segment_start + 1
    assert result.end_rank == segment_end
    assert result.total_count == segment_end - segment_start
    assert result.scanned_count == sample_limit
    assert [item.id for item in result.items] == [
        *range(segment_start, segment_start + sample_limit // 2),
        *range(segment_end - sample_limit // 2, segment_end),
    ]
    assert requested_pages == [(10, 19), (80, 89)]


def test_fetch_large_rank_score_segment_samples_real_head_and_tail(
    monkeypatch: MonkeyPatch,
) -> None:
    rank, _cache = _build_rank(
        online_limit=ONLINE_LIMIT,
        rank_limit=LARGE_SEGMENT_LIMIT,
        page_size=LARGE_SEGMENT_PAGE_SIZE,
        score_search_probe_limit=LARGE_SEGMENT_PROBE_LIMIT,
        score_search_tie_page_limit=TIED_PAGE_LIMIT,
    )
    requested_pages: list[tuple[int, int]] = []

    def score_at(index: int) -> int:
        if index < LARGE_SEGMENT_START_INDEX:
            return SEGMENT_SCORE + 1
        if index < LARGE_SEGMENT_END_INDEX:
            return SEGMENT_SCORE
        return SEGMENT_SCORE - 1

    async def fake_fetch_rank_item(
        *_args: object,
        index: int,
        **_kwargs: object,
    ) -> RankItem:
        return RankItem(id=index, nick=f"Player{index}", score=score_at(index))

    async def fake_fetch_rank_page_result(
        *_args: object,
        start: int,
        end: int,
        **_kwargs: object,
    ) -> RankPageResult:
        requested_pages.append((start, end))
        return RankPageResult(
            items=[
                RankItem(
                    id=index,
                    nick=f"Player{index}",
                    score=score_at(index),
                )
                for index in range(start, end + 1)
            ],
            fetched_at=FETCHED_AT,
        )

    monkeypatch.setattr(RankService, "fetch_item", fake_fetch_rank_item)
    monkeypatch.setattr(
        RankService,
        "fetch_page_result",
        fake_fetch_rank_page_result,
    )

    result = asyncio.run(
        rank.fetch_score_segment(
            GAME,
            title="standard peak",
            score_name="score",
            key=17,
            sub_key=0,
            target_score=SEGMENT_SCORE,
            sample_limit=LARGE_SEGMENT_SAMPLE_LIMIT,
        )
    )

    side_count = LARGE_SEGMENT_SAMPLE_LIMIT // 2
    assert result.start_rank == LARGE_SEGMENT_START_INDEX + 1
    assert result.end_rank == LARGE_SEGMENT_END_INDEX
    assert result.total_count == (
        LARGE_SEGMENT_END_INDEX - LARGE_SEGMENT_START_INDEX
    )
    assert not result.truncated
    assert [item.id for item in result.items] == [
        *range(
            LARGE_SEGMENT_START_INDEX,
            LARGE_SEGMENT_START_INDEX + side_count,
        ),
        *range(LARGE_SEGMENT_END_INDEX - side_count, LARGE_SEGMENT_END_INDEX),
    ]
    assert requested_pages == [(800, 899), (1100, 1199)]


def test_fetch_rank_score_segment_uses_cached_score_bounds_as_hint(
    monkeypatch: MonkeyPatch,
) -> None:
    rank, cache = _build_rank(
        online_limit=100,
        rank_limit=100,
        page_size=TIED_PAGE_SIZE,
        score_search_probe_limit=20,
        score_search_tie_page_limit=5,
    )
    requested_pages: list[tuple[int, int]] = []
    page_use_cache_values: list[bool] = []

    monkeypatch.setattr(
        cache,
        "summary",
        lambda **_: [
            RankPageSummary(start_index=20, end_index=29, min_score=150, max_score=200),
            RankPageSummary(start_index=30, end_index=39, min_score=150, max_score=150),
            RankPageSummary(start_index=40, end_index=49, min_score=100, max_score=150),
        ],
    )

    async def unexpected_fetch_rank_item(*_args: object, **_kwargs: object) -> None:
        raise AssertionError

    async def fake_fetch_rank_page_result(
        *_args: object,
        start: int,
        end: int,
        use_cache: bool = True,
        **_kwargs: object,
    ) -> RankPageResult:
        requested_pages.append((start, end))
        page_use_cache_values.append(use_cache)
        items = []
        for rank_index in range(start, end + 1):
            if rank_index < CACHED_HINT_SEGMENT_START_INDEX:
                score = 200
            elif rank_index < CACHED_HINT_SEGMENT_END_INDEX:
                score = SEGMENT_SCORE
            else:
                score = SEGMENT_BOUNDARY_SCORE
            items.append(
                RankItem(
                    id=rank_index,
                    nick=f"Player{rank_index}",
                    score=score,
                )
            )
        return RankPageResult(items=items, fetched_at=FETCHED_AT)

    monkeypatch.setattr(RankService, "fetch_item", unexpected_fetch_rank_item)
    monkeypatch.setattr(
        RankService,
        "fetch_page_result",
        fake_fetch_rank_page_result,
    )

    result = asyncio.run(
        rank.fetch_score_segment(
            GAME,
            title="mount",
            score_name="score",
            key=17,
            sub_key=0,
            target_score=SEGMENT_SCORE,
        )
    )

    assert requested_pages == [(20, 29), (30, 39), (40, 49)]
    assert page_use_cache_values == [False, False, False]
    assert result.start_rank == CACHED_HINT_SEGMENT_START_RANK
    assert result.end_rank == CACHED_HINT_SEGMENT_END_INDEX
    assert result.total_count == CACHED_HINT_SEGMENT_COUNT
    assert result.scanned_count == CACHED_HINT_SEGMENT_COUNT
    assert [item.id for item in result.items] == list(
        range(CACHED_HINT_SEGMENT_START_INDEX, CACHED_HINT_SEGMENT_END_INDEX)
    )


def test_fetch_rank_score_segment_uses_cached_score_facts_as_hint(
    monkeypatch: MonkeyPatch,
) -> None:
    rank, cache = _build_rank(
        online_limit=100,
        rank_limit=100,
        page_size=TIED_PAGE_SIZE,
        score_search_probe_limit=20,
        score_search_tie_page_limit=5,
    )
    requested_pages: list[tuple[int, int]] = []

    monkeypatch.setattr(
        cache,
        "score_indexes",
        lambda **_: [SEGMENT_START_INDEX],
    )

    async def unexpected_fetch_rank_item(*_args: object, **_kwargs: object) -> None:
        raise AssertionError

    async def fake_fetch_rank_page_result(
        *_args: object,
        start: int,
        end: int,
        **_kwargs: object,
    ) -> RankPageResult:
        requested_pages.append((start, end))
        items = []
        for rank_index in range(start, end + 1):
            score = SEGMENT_SCORE if rank_index == SEGMENT_START_INDEX else 200
            items.append(
                RankItem(
                    id=rank_index,
                    nick=f"Player{rank_index}",
                    score=score,
                )
            )
        return RankPageResult(items=items, fetched_at=FETCHED_AT)

    monkeypatch.setattr(RankService, "fetch_item", unexpected_fetch_rank_item)
    monkeypatch.setattr(
        RankService,
        "fetch_page_result",
        fake_fetch_rank_page_result,
    )

    result = asyncio.run(
        rank.fetch_score_segment(
            GAME,
            title="book",
            score_name="score",
            key=156,
            sub_key=1,
            target_score=SEGMENT_SCORE,
        )
    )

    assert requested_pages == [(20, 29), (10, 19)]
    assert result.start_rank == SEGMENT_START_RANK
    assert result.end_rank == SEGMENT_START_RANK
    assert result.total_count == 1
    assert [item.id for item in result.items] == [SEGMENT_START_INDEX]


def test_fetch_rank_score_segment_refreshes_cached_candidate_page(
    monkeypatch: MonkeyPatch,
) -> None:
    rank, cache = _build_rank(
        online_limit=100,
        rank_limit=100,
        page_size=TIED_PAGE_SIZE,
        score_search_probe_limit=20,
        score_search_tie_page_limit=5,
    )

    monkeypatch.setattr(
        cache,
        "summary",
        lambda **_: [
            RankPageSummary(
                start_index=50,
                end_index=59,
                item_count=10,
                expected_count=10,
                min_score=9970,
                max_score=10001,
                fetched_at=FETCHED_AT,
                is_stale=False,
                is_partial=False,
            )
        ],
    )
    monkeypatch.setattr(cache, "score_indexes", lambda **_: [])

    async def unexpected_fetch_rank_item(*_args: object, **_kwargs: object) -> None:
        raise AssertionError

    requested_pages: list[tuple[int, int, bool]] = []

    async def fresh_fetch_rank_page_result(
        _service: RankService,
        _game: object,
        *,
        key: int,
        sub_key: int,
        start: int,
        end: int,
        use_cache: bool = False,
    ) -> RankPageResult:
        _ = key, sub_key
        requested_pages.append((start, end, use_cache))
        return RankPageResult(
            items=[
                RankItem(id=1000 + index, nick=f"Player{index}", score=score)
                for index, score in enumerate(
                    [
                        10080,
                        10070,
                        10060,
                        10050,
                        10040,
                        10030,
                        10020,
                        10001,
                        10000,
                        9970,
                    ]
                )
            ],
            fetched_at=FETCHED_AT,
        )

    monkeypatch.setattr(RankService, "fetch_item", unexpected_fetch_rank_item)
    monkeypatch.setattr(
        RankService,
        "fetch_page_result",
        fresh_fetch_rank_page_result,
    )

    result = asyncio.run(
        rank.fetch_score_segment(
            GAME,
            title="autocard",
            score_name="score",
            key=240,
            sub_key=1,
            target_score=10000,
        )
    )

    assert requested_pages == [(50, 59, False)]
    assert [item.id for item in result.items] == [1008]
    assert result.start_rank == REFRESHED_CANDIDATE_RANK
    assert result.end_rank == REFRESHED_CANDIDATE_RANK
    assert result.total_count == 1
    assert result.fetched_at == FETCHED_AT


def test_fetch_rank_score_segment_proves_missing_score_from_binary_gap(
    monkeypatch: MonkeyPatch,
) -> None:
    missing_score = 175
    rank, _cache = _build_rank(
        rank_limit=100,
        page_size=TIED_PAGE_SIZE,
        score_search_probe_limit=20,
        score_search_tie_page_limit=5,
    )
    requested_pages: list[tuple[int, int]] = []

    async def fake_fetch_rank_item(
        *_args: object,
        index: int,
        **_kwargs: object,
    ) -> RankItem:
        score = ONLINE_GAP_UPPER_SCORE if index < SEGMENT_START_INDEX else SEGMENT_SCORE
        return RankItem(id=index, nick=f"Player{index}", score=score)

    async def fake_fetch_rank_page_result(
        *_args: object,
        start: int,
        end: int,
        **_kwargs: object,
    ) -> RankPageResult:
        requested_pages.append((start, end))
        items = []
        for rank_index in range(start, end + 1):
            score = (
                ONLINE_GAP_UPPER_SCORE
                if rank_index < SEGMENT_START_INDEX
                else SEGMENT_SCORE
            )
            items.append(
                RankItem(
                    id=rank_index,
                    nick=f"Player{rank_index}",
                    score=score,
                )
            )
        return RankPageResult(items=items, fetched_at=FETCHED_AT)

    monkeypatch.setattr(RankService, "fetch_item", fake_fetch_rank_item)
    monkeypatch.setattr(
        RankService,
        "fetch_page_result",
        fake_fetch_rank_page_result,
    )

    result = asyncio.run(
        rank.fetch_score_segment(
            GAME,
            title="book",
            score_name="score",
            key=156,
            sub_key=1,
            target_score=missing_score,
        )
    )

    assert result.items == []
    assert requested_pages == [(20, 29), (10, 19)]
    assert result.higher_gap is not None
    assert result.higher_gap.score == ONLINE_GAP_UPPER_SCORE
    assert result.higher_gap.start_rank == ONLINE_GAP_UPPER_START_RANK
    assert result.higher_gap.end_rank == ONLINE_GAP_UPPER_END_RANK
    assert result.lower_gap is not None
    assert result.lower_gap.score == SEGMENT_SCORE
    assert result.lower_gap.start_rank == ONLINE_GAP_LOWER_START_RANK
    assert result.lower_gap.end_rank == ONLINE_GAP_LOWER_END_RANK


def test_fetch_rank_score_segment_rejects_score_below_boundary(
    monkeypatch: MonkeyPatch,
) -> None:
    rank, _cache = _build_rank(rank_limit=100)
    requested_indexes: list[int] = []

    async def fake_fetch_rank_item(
        *_args: object,
        index: int,
        **_kwargs: object,
    ) -> RankItem:
        requested_indexes.append(index)
        return RankItem(
            id=index,
            nick=f"Player{index}",
            score=SEGMENT_BOUNDARY_SCORE,
        )

    monkeypatch.setattr(RankService, "fetch_item", fake_fetch_rank_item)

    result = asyncio.run(
        rank.fetch_score_segment(
            GAME,
            title="achievement",
            score_name="score",
            key=17,
            sub_key=0,
            target_score=99,
        )
    )

    assert result.boundary_score == SEGMENT_BOUNDARY_SCORE
    assert result.items == []
    assert requested_indexes == [99]


def test_fetch_rank_score_segment_handles_short_rank_board(
    monkeypatch: MonkeyPatch,
) -> None:
    rank, _cache = _build_rank(
        rank_limit=100,
        page_size=TIED_PAGE_SIZE,
        score_search_probe_limit=20,
        score_search_tie_page_limit=5,
    )
    actual_count = 60

    async def fake_fetch_rank_item(
        *_args: object,
        index: int,
        **_kwargs: object,
    ) -> RankItem | None:
        if index >= actual_count:
            return None
        if index < SEGMENT_START_INDEX:
            score = 200
        elif index < SEGMENT_END_INDEX:
            score = SEGMENT_SCORE
        else:
            score = SEGMENT_BOUNDARY_SCORE
        return RankItem(id=index, nick=f"Player{index}", score=score)

    async def fake_fetch_rank_page_result(
        *_args: object,
        start: int,
        end: int,
        **_kwargs: object,
    ) -> RankPageResult:
        items = []
        for rank_index in range(start, min(end + 1, actual_count)):
            if rank_index < SEGMENT_START_INDEX:
                score = 200
            elif rank_index < SEGMENT_END_INDEX:
                score = SEGMENT_SCORE
            else:
                score = SEGMENT_BOUNDARY_SCORE
            items.append(
                RankItem(
                    id=rank_index,
                    nick=f"Player{rank_index}",
                    score=score,
                )
            )
        return RankPageResult(items=items, fetched_at=FETCHED_AT)

    monkeypatch.setattr(RankService, "fetch_item", fake_fetch_rank_item)
    monkeypatch.setattr(
        RankService,
        "fetch_page_result",
        fake_fetch_rank_page_result,
    )

    result = asyncio.run(
        rank.fetch_score_segment(
            GAME,
            title="book",
            score_name="score",
            key=156,
            sub_key=1,
            target_score=SEGMENT_SCORE,
        )
    )

    assert result.boundary_score == SEGMENT_BOUNDARY_SCORE
    assert result.searched_limit == actual_count
    assert result.start_rank == SEGMENT_START_RANK
    assert result.end_rank == SEGMENT_END_INDEX
    assert result.total_count == SEGMENT_COUNT
    assert [item.id for item in result.items] == list(
        range(SEGMENT_START_INDEX, SEGMENT_END_INDEX)
    )


def test_fresh_cached_rank_is_verified_online_when_score_matches(
    monkeypatch: MonkeyPatch,
) -> None:
    rank, cache = _build_rank(online_limit=ONLINE_LIMIT, page_size=100)
    requested_ranges: list[tuple[int, int]] = []
    cached_item = CachedRankLookup(
        id=712345678,
        nick="cached",
        score=CACHED_SCORE,
        rank_index=LOOKUP_INDEX,
        fetched_at=FETCHED_AT,
        is_stale=False,
    )

    monkeypatch.setattr(cache, "item", lambda **_: cached_item)

    async def fake_fetch_rank_page(
        *_args: object,
        key: int,
        sub_key: int,
        start: int,
        end: int,
        use_cache: bool = True,
    ) -> list[RankItem]:
        _ = (key, sub_key)
        requested_ranges.append((start, end))
        assert use_cache is False
        return [
            RankItem(id=712345678, nick="fresh", score=CACHED_SCORE + 1),
        ]

    monkeypatch.setattr(RankService, "fetch_page", fake_fetch_rank_page)

    result = asyncio.run(
        rank.find_rank(
            GAME,
            user_id=712345678,
            title="book",
            score_name="score",
            key=156,
            sub_key=1,
            target_score=CACHED_SCORE,
        )
    )

    assert result.queried is True
    assert requested_ranges == [(0, 99), (0, 99)]
    assert result.rank == 1
    assert result.score == CACHED_SCORE + 1


def test_cached_rank_without_target_score_is_verified_nearby(
    monkeypatch: MonkeyPatch,
) -> None:
    rank, cache = _build_rank(online_limit=ONLINE_LIMIT, page_size=100)
    requested_ranges: list[tuple[int, int]] = []
    cached_item = CachedRankLookup(
        id=712345678,
        nick="cached",
        score=CACHED_SCORE,
        rank_index=LOOKUP_INDEX,
        fetched_at=FETCHED_AT,
        is_stale=False,
    )

    monkeypatch.setattr(cache, "item", lambda **_: cached_item)

    async def fake_fetch_rank_page(
        *_args: object,
        key: int,
        sub_key: int,
        start: int,
        end: int,
        use_cache: bool = True,
    ) -> list[RankItem]:
        _ = (key, sub_key, use_cache)
        requested_ranges.append((start, end))
        return [
            RankItem(id=712345678, nick="fresh", score=CACHED_SCORE + 1),
        ]

    monkeypatch.setattr(RankService, "fetch_page", fake_fetch_rank_page)

    result = asyncio.run(
        rank.find_rank(
            GAME,
            user_id=712345678,
            title="autocard",
            score_name="score",
            key=156,
            sub_key=1,
        )
    )

    assert requested_ranges == [(0, 99), (0, 99)]
    assert result.rank == 1
    assert result.score == CACHED_SCORE + 1


def test_cached_rank_confirms_its_own_page_before_expanding(
    monkeypatch: MonkeyPatch,
) -> None:
    rank, cache = _build_rank(online_limit=ONLINE_LIMIT, page_size=100)
    requested_ranges: list[tuple[int, int]] = []
    cached_item = CachedRankLookup(
        id=712345678,
        nick="cached",
        score=CACHED_SCORE,
        rank_index=109,
        fetched_at=FETCHED_AT,
        is_stale=True,
    )
    monkeypatch.setattr(cache, "item", lambda **_: cached_item)

    async def fake_fetch_rank_page(
        *_args: object,
        start: int,
        end: int,
        **_kwargs: object,
    ) -> list[RankItem]:
        requested_ranges.append((start, end))
        items = [RankItem(id=index, score=20_000 - index) for index in range(100)]
        items[49] = RankItem(id=712345678, nick="moved", score=CACHED_SCORE + 5)
        return items

    monkeypatch.setattr(RankService, "fetch_page", fake_fetch_rank_page)

    result = asyncio.run(
        rank.find_rank(
            GAME,
            user_id=712345678,
            title="book",
            score_name="score",
            key=156,
            sub_key=1,
            target_score=CACHED_SCORE,
        )
    )

    assert requested_ranges == [(100, 199), (0, 99), (100, 199)]
    assert result.rank == MOVED_RANK
    assert result.cost.lightweight_confirmed
    assert not result.cost.expanded


def test_anchor_only_rank_lookup_never_expands_beyond_cached_page(
    monkeypatch: MonkeyPatch,
) -> None:
    rank, cache = _build_rank(online_limit=ONLINE_LIMIT, page_size=100)
    requested_ranges: list[tuple[int, int]] = []
    cached_item = CachedRankLookup(
        id=712345678,
        nick="cached",
        score=CACHED_SCORE,
        rank_index=109,
        fetched_at=FETCHED_AT,
        is_stale=True,
    )
    monkeypatch.setattr(cache, "item", lambda **_: cached_item)

    async def fake_fetch_rank_page(
        *_args: object,
        start: int,
        end: int,
        **_kwargs: object,
    ) -> list[RankItem]:
        requested_ranges.append((start, end))
        return [RankItem(id=index, score=20_000 - index) for index in range(100)]

    monkeypatch.setattr(RankService, "fetch_page", fake_fetch_rank_page)

    result = asyncio.run(
        rank.find_rank(
            GAME,
            user_id=712345678,
            title="book",
            score_name="score",
            key=156,
            sub_key=1,
            target_score=CACHED_SCORE,
            anchor_only=True,
        )
    )

    assert requested_ranges == [(100, 199)]
    assert result.rank is None
    assert result.cost.restricted_miss
    assert not result.cost.expanded


def test_fetch_rank_item_fetches_aligned_page_on_cache_miss(
    monkeypatch: MonkeyPatch,
) -> None:
    rank, cache = _build_rank(page_size=100)
    requested_ranges: list[tuple[int, int]] = []

    monkeypatch.setattr(cache, "item_by_index", lambda **_: None)
    monkeypatch.setattr(cache, "save", lambda **_: None)

    class FakeGame:
        async def send_and_wait(
            self,
            *_args: object,
            **_kwargs: object,
        ) -> tuple[None, RankListResponse]:
            param = cast("RankRequestParam", _args[1])
            requested_ranges.append((param.start, param.end))
            return None, RankListResponse(
                rank_list=[
                    RankItem(id=index, nick=f"Player{index}", score=1000 - index)
                    for index in range(param.start, param.end + 1)
                ]
            )

    item = asyncio.run(
        rank.fetch_item(
            cast("SeerGame", FakeGame()),
            key=1,
            sub_key=2,
            index=LOOKUP_INDEX,
        )
    )

    assert requested_ranges == [(0, 99)]
    assert item is not None
    assert item.id == LOOKUP_INDEX


def test_daily_rank_page_result_fetches_aligned_page_and_slices(
    monkeypatch: MonkeyPatch,
) -> None:
    rank, _cache = _build_rank(page_size=100)
    requested_ranges: list[tuple[int, int]] = []

    async def fake_fetch_rank_page_result(
        *_args: object,
        key: int,
        sub_key: int,
        start: int,
        end: int,
        use_cache: bool = True,
    ) -> RankPageResult:
        _ = (key, sub_key, use_cache)
        requested_ranges.append((start, end))
        return RankPageResult(
            items=[
                RankItem(id=index, nick=f"Player{index}", score=1000 - index)
                for index in range(start, end + 1)
            ],
            fetched_at=FETCHED_AT,
        )

    monkeypatch.setattr(
        RankService,
        "fetch_page_result",
        fake_fetch_rank_page_result,
    )

    result = asyncio.run(
        rank.fetch_range_result(
            GAME,
            key=1,
            sub_key=2,
            start=LOOKUP_INDEX,
            count=1,
        )
    )

    assert requested_ranges == [(0, 99)]
    assert [item.id for item in result.items] == [LOOKUP_INDEX]
    assert result.fetched_at == FETCHED_AT
