# SPDX-License-Identifier: MIT
from pathlib import Path
from typing import Any, cast

import pytest

from ironsbot.config.models.seer import LocalRankConfig, PlayerQueryConfig
from ironsbot.integrations.storage.local_rank import SqliteLocalRankRepository
from ironsbot.services.seer.local_rank import LocalRankService
from ironsbot.services.seer.query_result import QueryReply


def test_binding_changes_control_samples_without_deleting_metrics(
    tmp_path: Path,
) -> None:
    eligible = frozenset({100001, 100002})
    repo = SqliteLocalRankRepository(
        tmp_path / "players.sqlite",
        100,
        eligible_player_ids=lambda: eligible,
    )
    key = "beast_beiming_completion"
    for player_id, value in ((100001, 100), (100002, 200), (100003, 50)):
        standings = repo.upsert_metrics(
            player_id=player_id,
            nick="sample",
            metrics={
                key: {
                    "value": value,
                    "season_sub_key": 1,
                }
            },
            clear_metric_keys=frozenset(),
            standing_inputs={key: (value, 1)},
        )
        if player_id not in eligible:
            assert standings == {}
    rows, count = repo.entries(key, limit=10, start_rank=1, season_sub_key=1)
    assert count == len(eligible)
    assert [row[1] for row in rows] == [100001, 100002]
    eligible = frozenset({100002, 100003})
    rows, count = repo.entries(key, limit=10, start_rank=1, season_sub_key=1)
    assert count == len(eligible)
    assert [row[1] for row in rows] == [100003, 100002]
    assert repo.entries(key, limit=10, start_rank=1, season_sub_key=2) == ([], 0)


def test_completion_sample_rank_uses_earlier_time_and_ties(tmp_path: Path) -> None:
    repo = SqliteLocalRankRepository(tmp_path / "players.sqlite", 100)
    key = "beast_beiming_completion"
    standings = {}
    for player_id, value in ((100001, 100), (100002, 100), (100003, 200)):
        standings = repo.upsert_metrics(
            player_id=player_id,
            nick="sample",
            metrics={
                key: {
                    "value": value,
                    "season_sub_key": 1,
                }
            },
            clear_metric_keys=frozenset(),
            standing_inputs={key: (value, 1)},
        )
    assert standings[key] == (3, 3, 1)
    rows, _ = repo.entries(key, limit=10, start_rank=1, season_sub_key=1)
    assert [row[0] for row in rows] == [1, 1, 3]


@pytest.mark.asyncio
async def test_cached_reply_recomputes_sample_after_unbinding(tmp_path: Path) -> None:
    eligible = frozenset({100001})
    repo = SqliteLocalRankRepository(
        tmp_path / "players.sqlite", 100, eligible_player_ids=lambda: eligible
    )
    service = LocalRankService(
        repo, LocalRankConfig(enabled=True), PlayerQueryConfig(), cast("Any", None)
    )
    metrics = {"autocard_score": {"value": 100, "season_sub_key": None}}
    await service.upsert_metrics(
        player_id=100001, nick="sample", current_metrics=metrics, peak_sub_key=None
    )

    def render() -> str:
        return "score:100 " + service.current_summary(
            100001, metrics, peak_sub_key=None
        ).sample_rank("autocard_score")

    reply = QueryReply(text=render(), refresh_text=render)
    assert "样本" in reply.text
    eligible = frozenset()
    refreshed = reply.refreshed()
    assert refreshed.text == "score:100 "
    assert repo.stats(()).total_player_count == 1
