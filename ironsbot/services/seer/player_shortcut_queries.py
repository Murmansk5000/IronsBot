# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from ironsbot.core.tasks import OperationDeadline
from ironsbot.core.time import ObservationTime
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
    format_player_extra_error,
    safe_player_extra,
    validate_player_peak_season,
)
from ironsbot.services.seer.query_result import QueryReply
from ironsbot.services.seer.rank_models import (
    PeakSeasonRankSummary,
    PlayerRankSummary,
    RankLookupResult,
    RankSummaryProgress,
)
from ironsbot.services.seer.rank_summary import fetch_partial_rank_summary
from ironsbot.services.seer.sequ_extra import (
    UnityPartOneInfo,
    UnityPeakInfo,
    fetch_unity_part_one,
    fetch_unity_peak_partial,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.local_rank import LocalRankService
    from ironsbot.services.seer.local_rank_metrics import MetricValue
    from ironsbot.services.seer.player_service_models import PlayerBaseSnapshot
    from ironsbot.services.seer.player_shortcut_contracts import (
        PlayerShortcutCommand,
        PlayerShortcutDependencies,
    )
    from ironsbot.services.seer.rank import RankService

logger = logging.getLogger(__name__)
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
_PEAK_METRIC_KEYS_BY_MODE: dict[str, frozenset[str]] = {
    "standard": frozenset(
        ("peak_standard", "peak_standard_win_rate", "peak_standard_matches")
    ),
    "wild": frozenset(("peak_wild", "peak_wild_win_rate", "peak_wild_matches")),
    "expert": frozenset(("peak_expert", "peak_expert_win_rate", "peak_expert_matches")),
}


async def fetch_player_shortcut_reply(
    dependencies: PlayerShortcutDependencies,
    game: Any,
    *,
    command: PlayerShortcutCommand,
    player_id: int,
    anchor_only: bool = False,
) -> QueryReply:
    deadline = OperationDeadline.after(dependencies.detail_timeout_seconds)
    if command.kind == "collection":
        return await _fetch_collection_message(
            dependencies.rank,
            dependencies.local_rank,
            game,
            player_id=player_id,
            base_snapshot=command.base_snapshot,
            timeout_seconds=dependencies.timeout_seconds,
            rank_timeout_seconds=dependencies.rank_timeout_seconds,
            deadline=deadline,
            anchor_only=anchor_only,
        )
    if command.kind == "peak":
        return await _fetch_peak_message(
            dependencies.rank,
            dependencies.local_rank,
            game,
            player_id=player_id,
            base_snapshot=command.base_snapshot,
            timeout_seconds=dependencies.timeout_seconds,
            rank_timeout_seconds=dependencies.rank_timeout_seconds,
            deadline=deadline,
            anchor_only=anchor_only,
        )
    return await _fetch_autocard_message(
        dependencies.rank,
        dependencies.local_rank,
        game,
        player_id=player_id,
        base_snapshot=command.base_snapshot,
        timeout_seconds=dependencies.timeout_seconds,
        rank_timeout_seconds=dependencies.rank_timeout_seconds,
        deadline=deadline,
        anchor_only=anchor_only,
    )


def _detail_reply(
    text: str,
    rank_lookups: tuple[RankLookupResult, ...],
    *,
    base_complete: bool,
) -> QueryReply:
    reply = QueryReply(text=text, rank_lookups=rank_lookups)
    return replace(reply, complete=base_complete and reply.rank_lookup_complete)


async def _fetch_collection_message(  # noqa: PLR0913
    rank: RankService,
    local_rank: LocalRankService,
    game: Any,
    *,
    player_id: int,
    base_snapshot: PlayerBaseSnapshot | None,
    timeout_seconds: float,
    rank_timeout_seconds: float,
    deadline: OperationDeadline,
    anchor_only: bool,
) -> QueryReply:
    extra_errors: list[str] = []
    observation = ObservationTime()
    (nick, nick_error), more_info, unity_part_one = await asyncio.gather(
        _resolve_shortcut_nick(
            game,
            player_id=player_id,
            base_snapshot=base_snapshot,
            timeout_seconds=deadline.remaining(timeout_seconds),
            observation=observation,
        ),
        _resolve_collection_more_info(
            game,
            player_id=player_id,
            base_snapshot=base_snapshot,
            timeout_seconds=deadline.remaining(timeout_seconds),
            extra_errors=extra_errors,
            observation=observation,
        ),
        safe_player_extra(
            "图鉴基础数据",
            observation.observe(lambda: fetch_unity_part_one(game, player_id)),
            UnityPartOneInfo(),
            extra_errors,
            on_error=_log_extra_error,
            timeout_seconds=deadline.remaining(timeout_seconds),
        ),
    )
    rank_progress = RankSummaryProgress()
    rank_summary = await fetch_partial_rank_summary(
        rank.fetch_player_summary(
            game,
            player_id,
            achieve_score=getattr(more_info, "total_achieve", None),
            pet_kind_count=unity_part_one.pet_kind_num,
            skin_score=unity_part_one.skin_num,
            progress=rank_progress,
            anchor_only=anchor_only,
        ),
        progress=rank_progress,
        build_partial=lambda results, failure: PlayerRankSummary.from_results(
            results,
            pet_kind_count=unity_part_one.pet_kind_num,
            failure=failure,
        ),
        timeout_seconds=deadline.remaining(rank_timeout_seconds),
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
    local_summary = await safe_player_extra(
        "样本数据",
        _update_selected_metrics(
            local_rank,
            player_id=player_id,
            nick=nick,
            metrics=metrics,
            allowed_keys=_COLLECTION_METRIC_KEYS,
            peak_sub_key=None,
        ),
        LocalRankSummary(),
        extra_errors,
        on_error=_log_extra_error,
        timeout_seconds=deadline.remaining(timeout_seconds),
    )
    message = _append_extra_errors(
        format_collection_info(
            more_info,
            unity_part_one=unity_part_one,
            rank_summary=rank_summary,
            local_summary=local_summary,
            fetched_at=_detail_observation_time(
                observation, _player_rank_results(rank_summary)
            ),
            player_identity=format_player_identity(
                player_id,
                nick,
                nick_error,
            ),
        ),
        extra_errors,
    )
    return _detail_reply(
        message,
        _player_rank_results(rank_summary),
        base_complete=not extra_errors and nick_error is None,
    )


async def _fetch_peak_message(  # noqa: PLR0913
    rank: RankService,
    local_rank: LocalRankService,
    game: Any,
    *,
    player_id: int,
    base_snapshot: PlayerBaseSnapshot | None,
    timeout_seconds: float,
    rank_timeout_seconds: float,
    deadline: OperationDeadline,
    anchor_only: bool,
) -> QueryReply:
    extra_errors: list[str] = []
    observation = ObservationTime()
    (nick, nick_error), peak_result = await asyncio.gather(
        _resolve_shortcut_nick(
            game,
            player_id=player_id,
            base_snapshot=base_snapshot,
            timeout_seconds=deadline.remaining(timeout_seconds),
            observation=observation,
        ),
        fetch_unity_peak_partial(
            game,
            player_id,
            timeout_seconds=deadline.remaining(timeout_seconds),
        ),
    )
    unity_peak = peak_result.info
    if peak_result.available_modes:
        observation.include(peak_result.fetched_at)
    for mode, error in peak_result.mode_errors:
        logger.warning("米米号详情字段获取失败：巅峰%s基础数据：%s", mode, error)
    peak_sub_key = rank.current_peak_sub_key()
    scores = calculate_player_peak_scores(
        unity_peak,
        available_modes=peak_result.available_modes,
    )
    peak_progress = RankSummaryProgress()
    rank_summary = await fetch_partial_rank_summary(
        rank.fetch_peak_summary(
            game,
            player_id,
            standard_score=scores.standard,
            wild_score=scores.wild,
            expert_score=scores.expert,
            progress=peak_progress,
            anchor_only=anchor_only,
        ),
        progress=peak_progress,
        build_partial=lambda results, failure: PeakSeasonRankSummary.from_results(
            results,
            failure=failure,
        ),
        timeout_seconds=deadline.remaining(rank_timeout_seconds),
    )
    validated_peak = validate_player_peak_season(
        unity_peak,
        scores,
        rank_summary,
        available_modes=peak_result.available_modes,
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
    peak_metric_keys = _peak_metric_keys_for_modes(peak_result.available_modes)
    local_summary = await safe_player_extra(
        "样本数据",
        _update_selected_metrics(
            local_rank,
            player_id=player_id,
            nick=nick,
            metrics=metrics,
            allowed_keys=peak_metric_keys,
            peak_sub_key=peak_sub_key,
            clear_metric_keys=validated_peak.clear_metric_keys,
        ),
        LocalRankSummary(),
        extra_errors,
        on_error=_log_extra_error,
        timeout_seconds=deadline.remaining(timeout_seconds),
    )
    message = _append_extra_errors(
        format_compact_peak_section(
            unity_peak,
            rank_summary,
            local_summary,
            fetched_at=_detail_observation_time(
                observation,
                (rank_summary.standard, rank_summary.wild, rank_summary.expert),
            ),
            player_id=player_id,
            nick=nick,
            nick_error=nick_error,
            available_modes=peak_result.available_modes,
            mode_errors=dict(peak_result.mode_errors),
        ),
        extra_errors,
    )
    return _detail_reply(
        message,
        (rank_summary.standard, rank_summary.wild, rank_summary.expert),
        base_complete=not extra_errors
        and nick_error is None
        and not peak_result.mode_errors,
    )


async def _fetch_autocard_message(  # noqa: PLR0913
    rank: RankService,
    local_rank: LocalRankService,
    game: Any,
    *,
    player_id: int,
    base_snapshot: PlayerBaseSnapshot | None,
    timeout_seconds: float,
    rank_timeout_seconds: float,
    deadline: OperationDeadline,
    anchor_only: bool,
) -> QueryReply:
    extra_errors: list[str] = []
    observation = ObservationTime()
    autocard_fallback = RankLookupResult(
        title="群星之巅榜",
        score_name="分",
    )

    def record_autocard_error(label: str, error: Exception) -> None:
        _log_extra_error(label, error)
        autocard_fallback.failure = format_player_extra_error(error)

    (nick, nick_error), result = await asyncio.gather(
        _resolve_shortcut_nick(
            game,
            player_id=player_id,
            base_snapshot=base_snapshot,
            timeout_seconds=deadline.remaining(timeout_seconds),
            observation=observation,
        ),
        safe_player_extra(
            "群星牌排行",
            rank.fetch_autocard_summary(
                game,
                player_id,
                anchor_only=anchor_only,
            ),
            autocard_fallback,
            None,
            on_error=record_autocard_error,
            timeout_seconds=deadline.remaining(rank_timeout_seconds),
        ),
    )
    metrics = {
        "autocard_score": {
            "value": result.score,
            "season_sub_key": None,
            "display": None,
        }
    }
    local_summary = await safe_player_extra(
        "样本数据",
        _update_selected_metrics(
            local_rank,
            player_id=player_id,
            nick=nick,
            metrics=metrics,
            allowed_keys=frozenset(("autocard_score",)),
            peak_sub_key=None,
        ),
        LocalRankSummary(),
        extra_errors,
        on_error=_log_extra_error,
        timeout_seconds=deadline.remaining(timeout_seconds),
    )
    message = _append_extra_errors(
        format_autocard_rank_info(
            result,
            player_identity=format_player_identity(
                player_id,
                nick,
                nick_error,
            ),
            local_summary=local_summary,
            fetched_at=_detail_observation_time(observation, (result,)),
        ),
        extra_errors,
    )
    return _detail_reply(
        message,
        (result,),
        base_complete=not extra_errors and nick_error is None,
    )


async def _resolve_shortcut_nick(
    game: Any,
    *,
    player_id: int,
    base_snapshot: PlayerBaseSnapshot | None,
    timeout_seconds: float,
    observation: ObservationTime,
) -> tuple[str, str | None]:
    if base_snapshot is not None and base_snapshot.player_id == player_id:
        observation.include(base_snapshot.fetched_at)
        return base_snapshot.nick, None
    try:
        user_info = await asyncio.wait_for(
            observation.observe(lambda: game.get_user_info(player_id)),
            timeout=timeout_seconds,
        )
    except Exception as error:  # noqa: BLE001
        _log_extra_error("玩家昵称", error)
        return "", format_player_extra_error(error)
    return str(getattr(user_info, "nick", "")), None


async def _resolve_collection_more_info(  # noqa: PLR0913
    game: Any,
    *,
    player_id: int,
    base_snapshot: PlayerBaseSnapshot | None,
    timeout_seconds: float,
    extra_errors: list[str],
    observation: ObservationTime,
) -> Any:
    if (
        base_snapshot is not None
        and base_snapshot.player_id == player_id
        and _has_collection_more_info(base_snapshot.more_info)
    ):
        observation.include(base_snapshot.fetched_at)
        return base_snapshot.more_info
    return await safe_player_extra(
        "收集基础数据",
        observation.observe(lambda: game.get_more_user_info(player_id)),
        SimpleNamespace(total_achieve=0, pet_all_num=0),
        extra_errors,
        on_error=_log_extra_error,
        timeout_seconds=timeout_seconds,
    )


def _has_collection_more_info(value: Any) -> bool:
    return hasattr(value, "total_achieve") and hasattr(value, "pet_all_num")


def _detail_observation_time(
    observation: ObservationTime, results: tuple[RankLookupResult, ...]
) -> float | None:
    for result in results:
        if result.rank is not None or (
            not result.failure and (result.score is not None or result.queried)
        ):
            observation.include(result.fetched_at)
    return observation.fetched_at


def _peak_metric_keys_for_modes(available_modes: frozenset[str]) -> frozenset[str]:
    keys = set().union(
        *(
            _PEAK_METRIC_KEYS_BY_MODE[mode]
            for mode in available_modes
            if mode in _PEAK_METRIC_KEYS_BY_MODE
        )
    )
    if available_modes == frozenset(("standard", "wild", "expert")):
        keys.add("peak_total_matches")
    return frozenset(keys)


def _player_rank_results(
    summary: PlayerRankSummary,
) -> tuple[RankLookupResult, ...]:
    breakdown = summary.breakdown
    return tuple(
        result
        for result in (
            summary.book,
            summary.achieve,
            breakdown.pet_kind,
            breakdown.skin,
            breakdown.countermark,
            breakdown.outfit_suit,
            breakdown.outfit_part,
            breakdown.mount,
        )
        if result is not None
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


def _append_extra_errors(message: str, errors: list[str]) -> str:
    if not errors:
        return message
    details = "\n".join(f"- {error}" for error in errors)
    return f"{message}\n\n⚠️ 部分数据查询失败：\n{details}"


def _log_extra_error(label: str, error: Exception) -> None:
    logger.warning(
        "米米号详情字段获取失败：%s",
        label,
        exc_info=(type(error), error, error.__traceback__),
    )
