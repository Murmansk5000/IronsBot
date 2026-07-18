# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Literal

from ironsbot.services.seer.local_rank_metrics import collect_metrics
from ironsbot.services.seer.local_rank_models import LocalRankSummary
from ironsbot.services.seer.player_collection_formatting import (
    format_autocard_rank_info,
    format_collection_info,
)
from ironsbot.services.seer.player_formatting_common import format_player_identity
from ironsbot.services.seer.player_peak_formatting import format_compact_peak_section
from ironsbot.services.seer.player_query import (
    calculate_player_peak_scores,
    validate_player_peak_season,
)
from ironsbot.services.seer.rank_models import PlayerRankSummary
from ironsbot.services.seer.rank_summary_runtime import (
    fetch_autocard_rank_summary,
    fetch_peak_season_rank_summary,
    fetch_player_rank_summary,
)
from ironsbot.services.seer.sequ_extra import (
    UnityPartOneInfo,
    UnityPeakInfo,
    fetch_unity_part_one,
    fetch_unity_peak,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.local_rank import LocalRankService
    from ironsbot.services.seer.local_rank_metrics import MetricValue

PlayerShortcutKind = Literal["collection", "peak", "autocard"]
_SHORTCUT_RE = re.compile(r"^(收集|巅峰|群星牌)(\d*)$")
_KIND_BY_COMMAND: dict[str, PlayerShortcutKind] = {
    "收集": "collection",
    "巅峰": "peak",
    "群星牌": "autocard",
}
_COLLECTION_METRIC_KEYS = frozenset(
    (
        "book_score",
        "achievement_score",
        "achievement_count",
        "pet_total_count",
        "pet_kind_count",
        "countermark_count",
        "outfit_suit_count",
        "outfit_part_count",
        "mount_count",
        "skin_count",
        "unlocked_book_entries",
    )
)
_PEAK_METRIC_KEYS = frozenset(
    (
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
    )
)


@dataclass(frozen=True, slots=True)
class PlayerShortcutCommand:
    kind: PlayerShortcutKind
    player_id: int | None


def parse_player_shortcut_command(text: str) -> PlayerShortcutCommand | None:
    normalized = "".join(text.split())
    match = _SHORTCUT_RE.fullmatch(normalized)
    if match is None:
        return None
    command, player_id_text = match.groups()
    return PlayerShortcutCommand(
        kind=_KIND_BY_COMMAND[command],
        player_id=int(player_id_text) if player_id_text else None,
    )


async def fetch_player_shortcut_message(
    local_rank: LocalRankService,
    game: Any,
    *,
    command: PlayerShortcutCommand,
    player_id: int,
) -> str:
    if command.kind == "collection":
        return await _fetch_collection_message(
            local_rank,
            game,
            player_id=player_id,
        )
    if command.kind == "peak":
        return await _fetch_peak_message(
            local_rank,
            game,
            player_id=player_id,
        )
    return await _fetch_autocard_message(
        local_rank,
        game,
        player_id=player_id,
    )


async def _fetch_collection_message(
    local_rank: LocalRankService,
    game: Any,
    *,
    player_id: int,
) -> str:
    user_info, more_info, unity_part_one = await asyncio.gather(
        game.get_user_info(player_id),
        game.get_more_user_info(player_id),
        fetch_unity_part_one(game, player_id),
    )
    rank_summary = await fetch_player_rank_summary(
        game,
        player_id,
        achieve_score=getattr(more_info, "total_achieve", None),
        pet_kind_count=unity_part_one.pet_kind_num,
        skin_score=unity_part_one.skin_num,
    )
    metrics = collect_metrics(
        more_info=more_info,
        unity_part_one=unity_part_one,
        unity_peak=UnityPeakInfo(),
        rank_summary=rank_summary,
        autocard_rank_summary=None,
        peak_sub_key=None,
        peak_standard_score=None,
        peak_wild_score=None,
        peak_expert_score=None,
    )
    local_summary = await _update_selected_metrics(
        local_rank,
        player_id=player_id,
        nick=str(user_info.nick),
        metrics=metrics,
        allowed_keys=_COLLECTION_METRIC_KEYS,
        peak_sub_key=None,
    )
    return format_collection_info(
        more_info,
        unity_part_one=unity_part_one,
        rank_summary=rank_summary,
        local_summary=local_summary,
        player_identity=format_player_identity(player_id, user_info.nick),
    )


async def _fetch_peak_message(
    local_rank: LocalRankService,
    game: Any,
    *,
    player_id: int,
) -> str:
    user_info, unity_peak = await asyncio.gather(
        game.get_user_info(player_id),
        fetch_unity_peak(game, player_id),
    )
    peak_sub_key = local_rank.current_peak_sub_key()
    scores = calculate_player_peak_scores(unity_peak)
    rank_summary = await fetch_peak_season_rank_summary(
        game,
        player_id,
        standard_score=scores.standard,
        wild_score=scores.wild,
        expert_score=scores.expert,
    )
    validated_peak = validate_player_peak_season(
        unity_peak,
        scores,
        rank_summary,
    )
    metrics = collect_metrics(
        more_info=SimpleNamespace(total_achieve=0, pet_all_num=0),
        unity_part_one=UnityPartOneInfo(),
        unity_peak=validated_peak.unity_peak,
        rank_summary=PlayerRankSummary.empty(),
        autocard_rank_summary=None,
        peak_sub_key=peak_sub_key,
        peak_standard_score=validated_peak.scores.standard,
        peak_wild_score=validated_peak.scores.wild,
        peak_expert_score=validated_peak.scores.expert,
    )
    for metric_key in validated_peak.clear_metric_keys:
        metrics.pop(metric_key, None)
    local_summary = await _update_selected_metrics(
        local_rank,
        player_id=player_id,
        nick=str(user_info.nick),
        metrics=metrics,
        allowed_keys=_PEAK_METRIC_KEYS,
        peak_sub_key=peak_sub_key,
        clear_metric_keys=validated_peak.clear_metric_keys,
    )
    return format_compact_peak_section(
        unity_peak,
        rank_summary,
        local_summary,
        player_id=player_id,
        nick=str(user_info.nick),
    )


async def _fetch_autocard_message(
    local_rank: LocalRankService,
    game: Any,
    *,
    player_id: int,
) -> str:
    user_info, result = await asyncio.gather(
        game.get_user_info(player_id),
        fetch_autocard_rank_summary(game, player_id),
    )
    metrics = {
        "autocard_score": {
            "value": result.score,
            "season_sub_key": None,
            "display": None,
        }
    }
    local_summary = await _update_selected_metrics(
        local_rank,
        player_id=player_id,
        nick=str(user_info.nick),
        metrics=metrics,
        allowed_keys=frozenset(("autocard_score",)),
        peak_sub_key=None,
    )
    return format_autocard_rank_info(
        result,
        player_identity=format_player_identity(player_id, user_info.nick),
        local_summary=local_summary,
    )


async def _update_selected_metrics(  # noqa: PLR0913
    local_rank: LocalRankService,
    *,
    player_id: int,
    nick: str,
    metrics: dict[str, MetricValue],
    allowed_keys: frozenset[str],
    peak_sub_key: int | None,
    clear_metric_keys: frozenset[str] = frozenset(),
) -> LocalRankSummary:
    selected = {
        key: value
        for key, value in metrics.items()
        if key in allowed_keys and value.get("value") is not None
    }
    if not local_rank.config.enabled or (not selected and not clear_metric_keys):
        return LocalRankSummary()
    return await local_rank.upsert_metrics(
        player_id=player_id,
        nick=nick,
        current_metrics=selected,
        peak_sub_key=peak_sub_key,
        clear_metric_keys=clear_metric_keys & allowed_keys,
    )
