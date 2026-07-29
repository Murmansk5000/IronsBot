from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.config.models.seer import LocalRankConfig, PlayerQueryConfig
from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.integrations.storage.local_rank import SqliteLocalRankRepository
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionAction,
)
from ironsbot.services.seer.player_query import (
    PLAYER_AUTOCARD_KEY,
    PLAYER_COLLECTION_KEY,
    PLAYER_PEAK_KEY,
    PlayerDetailPromptPlan,
    PlayerPeakScores,
    PlayerQuerySectionPlan,
    extract_player_query_arg,
    plan_player_detail_prompt,
    plan_player_query_sections,
    resolve_player_detail_reply,
    validate_player_peak_season,
)
from ironsbot.services.seer.query_result import QueryReply
from ironsbot.services.seer.rank_models import PeakSeasonRankSummary, RankLookupResult
from ironsbot.services.seer.sequ_extra import UnityPartOneInfo, UnityPeakInfo

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.services.operations.headless import HeadlessGame
    from ironsbot.services.seer.rank import RankService

EXPERT_SCORE = 1142
EXPERT_WINS = 8
EXPERT_MATCHES = 9


def test_extract_player_query_arg_accepts_explicit_and_default_forms() -> None:
    assert extract_player_query_arg("米米号123456") == "123456"
    assert extract_player_query_arg("米米号") == ""
    assert extract_player_query_arg("not a player command") is None


def test_player_detail_resolver_accepts_only_current_menu_numbers() -> None:
    selections = (
        ("1", PLAYER_COLLECTION_KEY),
        ("2", PLAYER_PEAK_KEY),
        ("3", PLAYER_AUTOCARD_KEY),
    )

    collection = resolve_player_detail_reply("1", selections=selections)
    peak = resolve_player_detail_reply("2", selections=selections)

    assert collection is not None
    assert collection.key == PLAYER_COLLECTION_KEY
    assert peak is not None
    assert peak.key == PLAYER_PEAK_KEY
    assert resolve_player_detail_reply("收集", selections=selections) is None
    assert resolve_player_detail_reply("巅峰", selections=selections) is None
    assert resolve_player_detail_reply("阵容", selections=selections) is None


def test_plan_player_query_sections_maps_configured_sections() -> None:
    plan = plan_player_query_sections(
        ("basic", "collection", "local_rank", "peak", "autocard"),
        local_rank_enabled=True,
    )

    assert plan == PlayerQuerySectionPlan(
        show_local_rank=True,
        has_collection=True,
        needs_peak_section=True,
        has_autocard_rank=True,
        needs_online_info=True,
        local_rank_enabled=True,
    )


def test_peak_validation_clears_unconfirmed_current_season_values() -> None:
    peak = UnityPeakInfo(
        current_j_rank=4,
        current_j_star=12,
        current_j_win=30,
        current_j_all=40,
        current_k_rank=3,
        current_k_star=20,
        current_k_win=12,
        current_k_all=30,
        current_z_score=EXPERT_SCORE,
        current_z_win=EXPERT_WINS,
        current_z_all=EXPERT_MATCHES,
    )

    validated = validate_player_peak_season(
        peak,
        PlayerPeakScores(400012, 300020, EXPERT_SCORE),
        PeakSeasonRankSummary.empty(),
    )

    assert validated.scores == PlayerPeakScores()
    assert validated.unity_peak.current_j_rank == 0
    assert validated.unity_peak.current_j_star == 0
    assert validated.unity_peak.current_j_win == 0
    assert validated.unity_peak.current_j_all == 0
    assert validated.unity_peak.current_k_rank == 0
    assert validated.unity_peak.current_k_star == 0
    assert validated.unity_peak.current_k_win == 0
    assert validated.unity_peak.current_k_all == 0
    assert validated.unity_peak.current_z_score == 0
    assert validated.unity_peak.current_z_win == 0
    assert validated.unity_peak.current_z_all == 0
    assert validated.clear_metric_keys == frozenset(
        {
            "peak_standard",
            "peak_standard_win_rate",
            "peak_standard_matches",
            "peak_wild",
            "peak_wild_win_rate",
            "peak_wild_matches",
            "peak_expert",
            "peak_expert_win_rate",
            "peak_expert_matches",
            "peak_total_matches",
        }
    )


def test_peak_validation_keeps_values_confirmed_by_current_season_rank() -> None:
    peak = UnityPeakInfo(
        current_z_score=EXPERT_SCORE,
        current_z_win=EXPERT_WINS,
        current_z_all=EXPERT_MATCHES,
    )
    summary = PeakSeasonRankSummary.empty()
    summary.expert = RankLookupResult(
        title="专家赛季榜",
        score_name="专家积分",
        rank=88,
        score=EXPERT_SCORE,
        queried=True,
    )

    validated = validate_player_peak_season(
        peak,
        PlayerPeakScores(expert=EXPERT_SCORE),
        summary,
    )

    assert validated.scores.expert == EXPERT_SCORE
    assert validated.unity_peak.current_z_score == EXPERT_SCORE
    assert validated.unity_peak.current_z_win == EXPERT_WINS
    assert validated.unity_peak.current_z_all == EXPERT_MATCHES
    assert not (validated.clear_metric_keys & {
        "peak_expert",
        "peak_expert_win_rate",
        "peak_expert_matches",
    })


@pytest.mark.asyncio
async def test_local_rank_refresh_clears_unconfirmed_peak_metrics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from ironsbot.services.seer import local_rank
    from ironsbot.services.seer.local_rank import LocalRankService

    rank = SimpleNamespace(
        fetch_player_summary=AsyncMock(),
        fetch_peak_summary=AsyncMock(return_value=PeakSeasonRankSummary.empty()),
    )
    service = LocalRankService(
        repository=SqliteLocalRankRepository(tmp_path / "local-rank.sqlite", 100),
        config=LocalRankConfig(path=tmp_path / "local-rank.sqlite"),
        player_config=PlayerQueryConfig(),
        rank=cast("RankService", rank),
    )
    update_cache = AsyncMock()
    monkeypatch.setattr(LocalRankService, "update_cache", update_cache)
    monkeypatch.setattr(
        local_rank,
        "fetch_unity_part_one",
        AsyncMock(return_value=UnityPartOneInfo()),
    )
    monkeypatch.setattr(
        local_rank,
        "fetch_unity_peak",
        AsyncMock(
            return_value=UnityPeakInfo(
                current_z_score=EXPERT_SCORE,
                current_z_win=EXPERT_WINS,
                current_z_all=EXPERT_MATCHES,
            )
        ),
    )

    await service._refresh_one(
        game=cast(
            "HeadlessGame",
            SimpleNamespace(
                get_user_info=AsyncMock(return_value=SimpleNamespace(nick="测试")),
                get_more_user_info=AsyncMock(return_value=SimpleNamespace()),
            ),
        ),
        peak_sub_key=20260717,
        player_id=201178335,
    )

    assert rank.fetch_peak_summary.await_args is not None
    assert rank.fetch_peak_summary.await_args.kwargs["anchor_only"] is True
    update_call = update_cache.await_args
    assert update_call is not None
    stored = update_call.kwargs
    assert stored["unity_peak"].current_z_score == 0
    assert stored["unity_peak"].current_z_all == 0
    assert stored["peak_expert_score"] is None
    assert "peak_expert" in stored["clear_metric_keys"]


def test_player_detail_prompt_assigns_standard_menu_numbers_in_registration_order(
) -> None:
    extension = PlayerDetailExtensionAction(
        id="private_action",
        feature="private_feature",
        label="private action",
        aliases=("private",),
        query=AsyncMock(return_value=QueryReply(text="ok")),
        action=ActionDefinition("private_action", "private action"),
    )

    plan = plan_player_detail_prompt(
        has_collection=True,
        has_peak=True,
        has_autocard=True,
        supports_conversation=True,
        extension_actions=(extension,),
    )

    assert plan == PlayerDetailPromptPlan(
        accepted_commands=(
            "1",
            "2",
            "3",
            "4",
            "0",
        ),
        prompt_lines=(
            "回复数字查看详情：",
            "1.【收集】",
            "2.【巅峰】",
            "3.【群星牌】",
            "4.【private action】",
            "0.【退出】",
        ),
        builtin_selections=(
            ("1", PLAYER_COLLECTION_KEY),
            ("2", PLAYER_PEAK_KEY),
            ("3", PLAYER_AUTOCARD_KEY),
        ),
        extension_selections=(("4", "private_action"),),
        should_enter_conversation=True,
    )


def test_player_detail_prompt_uses_registered_extension_actions() -> None:
    extension = PlayerDetailExtensionAction(
        id="private_action",
        feature="private_feature",
        label="private action",
        aliases=("private",),
        query=AsyncMock(return_value=QueryReply(text="ok")),
        action=ActionDefinition("private_action", "private action"),
    )

    plan = plan_player_detail_prompt(
        has_collection=False,
        has_peak=True,
        has_autocard=False,
        supports_conversation=True,
        extension_actions=(extension,),
    )

    assert plan == PlayerDetailPromptPlan(
        accepted_commands=("1", "2", "0"),
        prompt_lines=(
            "回复数字查看详情：",
            "1.【巅峰】",
            "2.【private action】",
            "0.【退出】",
        ),
        builtin_selections=(("1", PLAYER_PEAK_KEY),),
        extension_selections=(("2", "private_action"),),
        should_enter_conversation=True,
    )
