from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ironsbot.config.models.seer import LocalRankConfig, PlayerQueryConfig
from ironsbot.integrations.storage.local_rank import SqliteLocalRankRepository
from ironsbot.services.seer.local_rank import LocalRankService
from ironsbot.services.seer.local_rank_formatting import format_metric_display
from ironsbot.services.seer.value_coercion import coerce_positive_int

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.services.seer.local_rank_metrics import MetricValue

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
        None,
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
