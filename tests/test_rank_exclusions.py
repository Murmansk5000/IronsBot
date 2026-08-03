import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest
from pydantic import ValidationError

from ironsbot.config.models.seer import RankExclusionConfig, RankQueryConfig
from ironsbot.core.rank_exclusions import (
    DEFAULT_RANK_EXCLUSION_USER_IDS_BY_RANK,
    DEFAULT_TAOMEE_INTERNAL_USER_IDS,
)
from ironsbot.services.seer.rank import RankService
from ironsbot.services.seer.rank_exclusions import RankExclusionPolicy
from ironsbot.services.seer.rank_models import RankEntry

if TYPE_CHECKING:
    from ironsbot.services.operations.headless import HeadlessGame
    from ironsbot.services.seer.rank import RankPageCache

PET_KIND_SCORE = 657
GAME = cast("HeadlessGame", object())


@dataclass
class FakeRankCache:
    saved: list[tuple[int, int, int, int]]

    def page(self, **_kwargs: object) -> None:
        return None

    def save(
        self,
        *,
        key: int,
        sub_key: int,
        start: int,
        end: int,
        **_kwargs: object,
    ) -> None:
        self.saved.append((key, sub_key, start, end))


def _rank(entries: list[RankEntry]) -> RankService:
    async def fetch_online_page(
        _game: object,
        *,
        start: int,
        end: int,
        **_kwargs: object,
    ) -> list[RankEntry]:
        return entries[start : end + 1]

    return RankService(
        RankQueryConfig(limit=10, page_size=100),
        cast("RankPageCache", FakeRankCache([])),
        lambda: None,
        fetch_online_page,
    )


def test_policy_keeps_per_rank_anomalies_out_of_other_ranks_and_samples() -> None:
    policy = RankExclusionPolicy.from_config()
    normal_anomaly = DEFAULT_RANK_EXCLUSION_USER_IDS_BY_RANK["精灵图鉴"][0]
    taomee_user = DEFAULT_TAOMEE_INTERNAL_USER_IDS[0]

    assert policy.excludes_from_public_rank("精灵图鉴", normal_anomaly)
    assert not policy.excludes_from_public_rank("成就点数", normal_anomaly)
    assert not policy.excludes_from_sample(normal_anomaly)
    assert policy.excludes_from_public_rank("成就点数", taomee_user)
    assert policy.excludes_from_sample(taomee_user)


def test_public_pet_kind_rank_filters_configured_accounts_and_renumbers() -> None:
    excluded = [
        *DEFAULT_TAOMEE_INTERNAL_USER_IDS,
        *DEFAULT_RANK_EXCLUSION_USER_IDS_BY_RANK["精灵图鉴"],
    ]
    rank = _rank(
        [
            *(RankEntry(user_id, f"excluded-{user_id}", 9_999) for user_id in excluded),
            RankEntry(298227103, "车载慢摇", 4_896),
            RankEntry(123456789, "正常玩家", 4_895),
        ]
    )

    result = asyncio.run(
        rank.fetch_visible_range_result(
            GAME,
            rank_key="精灵图鉴",
            key=158,
            sub_key=1,
            start_rank=1,
            count=2,
        )
    )

    assert [item.id for item in result.items] == [298227103, 123456789]


def test_pet_kind_score_lookup_filters_only_that_rank() -> None:
    rank = _rank(
        [
            RankEntry(960649568, "异常精灵图鉴", 100),
            RankEntry(123456789, "正常玩家", 100),
            RankEntry(298227103, "下一名", 99),
        ]
    )

    result = asyncio.run(
        rank.fetch_score_segment(
            GAME,
            rank_key="精灵图鉴",
            key=158,
            sub_key=1,
            title="精灵图鉴榜",
            score_name="项",
            target_score=100,
        )
    )

    assert [(item.id, item.rank_index) for item in result.items] == [(123456789, 0)]
    assert (result.start_rank, result.end_rank, result.total_count) == (1, 1, 1)


def test_excluded_player_is_marked_without_querying_rank_pages() -> None:
    rank = _rank([])

    result = asyncio.run(
        rank.find_pet_kind_rank(
            GAME,
            user_id=960649568,
            pet_kind_count=PET_KIND_SCORE,
            search_limit=10,
        )
    )

    assert result.excluded
    assert result.rank is None
    assert result.score == PET_KIND_SCORE


def test_rank_exclusion_config_rejects_unknown_rank_and_non_positive_ids() -> None:
    with pytest.raises(ValidationError, match="unsupported rank key"):
        RankExclusionConfig(user_ids_by_rank={"不存在的榜": (1,)})
    with pytest.raises(ValidationError, match="must be positive"):
        RankExclusionConfig(taomee_internal_user_ids=(0,))


def test_rank_exclusion_config_deduplicates_ids() -> None:
    config = RankExclusionConfig(
        taomee_internal_user_ids=(1, 1, 2),
        user_ids_by_rank={"精灵图鉴": (3, 3, 4)},
    )

    assert config.taomee_internal_user_ids == (1, 2)
    assert config.user_ids_by_rank["精灵图鉴"] == (3, 4)
