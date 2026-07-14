import pytest

from ironsbot.services.seer.rank_constants import (
    ACHIEVE_RANK_KEY,
    EXPERT_PEAK_USER_RANK_KEY,
    SKIN_RANK_KEY,
    WILD_PEAK_USER_RANK_KEY,
)
from ironsbot.services.seer.rank_models import RankLookupResult
from ironsbot.services.seer.rank_summary import (
    fetch_peak_season_rank_summary,
    fetch_player_rank_summary,
)

USER_ID = 123456
FOUND_RANK = 7
PET_KIND_COUNT = 100
SKIN_SCORE = 10
ACHIEVE_SCORE = 56
PEAK_SCORE = 400100
EXPERT_SCORE = 2500


def _int_kwarg(kwargs: dict[str, object], name: str, default: int = 0) -> int:
    value = kwargs.get(name)
    return value if isinstance(value, int) else default


async def _rank_success(_game: object, **kwargs: object) -> RankLookupResult:
    return RankLookupResult(
        title=str(kwargs["title"]),
        score_name=str(kwargs["score_name"]),
        rank=FOUND_RANK,
        score=_int_kwarg(kwargs, "target_score", 10),
        searched_limit=_int_kwarg(kwargs, "search_limit"),
        queried=True,
    )


async def _pet_kind_success(_game: object, **kwargs: object) -> RankLookupResult:
    return RankLookupResult(
        title="精灵图鉴",
        score_name="精灵",
        rank=8,
        score=_int_kwarg(kwargs, "pet_kind_count"),
        queried=True,
    )


@pytest.mark.asyncio
async def test_player_rank_summary_keeps_other_items_when_one_rank_times_out() -> None:
    async def find_rank(game: object, **kwargs: object) -> RankLookupResult:
        if kwargs["key"] in {ACHIEVE_RANK_KEY, SKIN_RANK_KEY}:
            raise TimeoutError
        return await _rank_success(game, **kwargs)

    summary = await fetch_player_rank_summary(
        object(),
        USER_ID,
        achieve_score=ACHIEVE_SCORE,
        pet_kind_count=PET_KIND_COUNT,
        skin_score=SKIN_SCORE,
        book_breakdown_limit=2000,
        find_rank=find_rank,
        find_pet_kind_rank=_pet_kind_success,
    )

    assert summary.book.queried
    assert summary.book.rank == FOUND_RANK
    assert not summary.achieve.queried
    assert summary.achieve.score == ACHIEVE_SCORE
    assert summary.breakdown.pet_kind is not None
    assert summary.breakdown.skin is not None
    assert summary.breakdown.countermark is not None
    assert summary.breakdown.pet_kind.queried
    assert not summary.breakdown.skin.queried
    assert summary.breakdown.skin.score == SKIN_SCORE
    assert summary.breakdown.countermark.queried


@pytest.mark.asyncio
async def test_peak_rank_summary_keeps_other_modes_when_one_rank_times_out() -> None:
    async def find_rank(game: object, **kwargs: object) -> RankLookupResult:
        if kwargs["key"] == WILD_PEAK_USER_RANK_KEY:
            raise TimeoutError
        return await _rank_success(game, **kwargs)

    summary = await fetch_peak_season_rank_summary(
        object(),
        USER_ID,
        standard_score=PEAK_SCORE,
        wild_score=PEAK_SCORE,
        expert_score=EXPERT_SCORE,
        current_peak_sub_key=42,
        find_rank=find_rank,
    )

    assert summary.standard.queried
    assert summary.standard.rank == FOUND_RANK
    assert not summary.wild.queried
    assert summary.wild.score == PEAK_SCORE
    assert summary.expert.queried
    assert summary.expert.score == EXPERT_SCORE


@pytest.mark.asyncio
async def test_peak_rank_summary_keeps_expert_score_when_expert_times_out() -> None:
    async def find_rank(game: object, **kwargs: object) -> RankLookupResult:
        if kwargs["key"] == EXPERT_PEAK_USER_RANK_KEY:
            raise TimeoutError
        return await _rank_success(game, **kwargs)

    summary = await fetch_peak_season_rank_summary(
        object(),
        USER_ID,
        standard_score=0,
        wild_score=0,
        expert_score=EXPERT_SCORE,
        current_peak_sub_key=42,
        find_rank=find_rank,
    )

    assert not summary.expert.queried
    assert summary.expert.score == EXPERT_SCORE
