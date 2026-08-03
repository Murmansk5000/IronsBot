from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.config.models.seer import LocalRankConfig, PlayerQueryConfig
from ironsbot.core.rank_exclusions import (
    DEFAULT_RANK_EXCLUSION_USER_IDS_BY_RANK,
    DEFAULT_TAOMEE_INTERNAL_USER_IDS,
)
from ironsbot.integrations.storage.local_rank import SqliteLocalRankRepository
from ironsbot.services.seer.local_rank import LocalRankService
from ironsbot.services.seer.local_rank_formatting import format_metric_display
from ironsbot.services.seer.rank_exclusions import RankExclusionPolicy
from ironsbot.services.seer.value_coercion import coerce_positive_int

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.services.seer.local_rank_metrics import MetricValue
    from ironsbot.services.seer.rank import RankService

EXPECTED_POSITIVE_INT = 12


def test_coerce_positive_int_rejects_invalid_and_non_positive_values() -> None:
    assert coerce_positive_int(str(EXPECTED_POSITIVE_INT)) == EXPECTED_POSITIVE_INT
    assert coerce_positive_int(0) is None
    assert coerce_positive_int(-1) is None
    assert coerce_positive_int("invalid") is None


def test_format_metric_display_decodes_peak_scores() -> None:
    assert format_metric_display("peak_standard", 400036) == "圣皇36星"
    assert format_metric_display("peak_standard", 400100) == "宇宙圣皇100星"
    assert format_metric_display("peak_wild", 300065) == "王者65星"
    assert format_metric_display("peak_expert", 1155) == "1155分"


def test_format_metric_display_keeps_cached_display_text() -> None:
    assert format_metric_display("peak_standard", 400036, "圣皇36星") == "圣皇36星"
    assert format_metric_display("book_score", 12345) == "12345"


@pytest.mark.asyncio
async def test_upsert_local_rank_metrics_clears_unconfirmed_peak_metrics(
    tmp_path: Path,
) -> None:
    path = tmp_path / "local-rank.sqlite"
    config = LocalRankConfig(path=path)
    service = LocalRankService(
        SqliteLocalRankRepository(path, config.max_players),
        config,
        PlayerQueryConfig(),
        cast("RankService", object()),
    )
    metrics: dict[str, MetricValue] = {
        "peak_wild": {"value": 400100, "season_sub_key": 20260717},
        "achievement_score": {"value": 5000},
    }
    await service.upsert_metrics(
        player_id=123456,
        nick="旧玩家",
        current_metrics=metrics,
        peak_sub_key=20260717,
    )
    await service.upsert_metrics(
        player_id=123456,
        nick="当前玩家",
        current_metrics={},
        peak_sub_key=20260717,
        clear_metric_keys=frozenset(("peak_wild",)),
    )

    peak_entries, _ = service.entries(
        "peak_wild",
        limit=10,
        start_rank=1,
        season_sub_key=20260717,
    )
    achievement_entries, _ = service.entries(
        "achievement_score",
        limit=10,
        start_rank=1,
        season_sub_key=None,
    )
    assert peak_entries == []
    assert [entry.user_id for entry in achievement_entries] == [123456]


@pytest.mark.asyncio
async def test_local_samples_only_exclude_taomee_internal_accounts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "local-rank.sqlite"
    config = LocalRankConfig(path=path)
    repository = SqliteLocalRankRepository(path, config.max_players)
    service = LocalRankService(
        repository,
        config,
        PlayerQueryConfig(),
        cast("RankService", object()),
        exclusions=RankExclusionPolicy.from_config(),
    )
    taomee_user = DEFAULT_TAOMEE_INTERNAL_USER_IDS[0]
    pet_kind_only_anomaly = DEFAULT_RANK_EXCLUSION_USER_IDS_BY_RANK[
        "精灵图鉴"
    ][0]

    assert not service.can_cache(taomee_user)
    assert service.can_cache(pet_kind_only_anomaly)

    await service.upsert_metrics(
        player_id=taomee_user,
        nick="内部号",
        current_metrics={"book_score": {"value": 9_999}},
        peak_sub_key=None,
    )
    await service.upsert_metrics(
        player_id=pet_kind_only_anomaly,
        nick="正常异常号",
        current_metrics={"book_score": {"value": 8_888}},
        peak_sub_key=None,
    )

    entries, _sample_count = service.entries(
        "book_score",
        limit=10,
        start_rank=1,
        season_sub_key=None,
    )
    assert [entry.user_id for entry in entries] == [pet_kind_only_anomaly]
