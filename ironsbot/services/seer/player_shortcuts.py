# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Literal

from ironsbot.core.semantic_requests import (
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    SemanticTarget,
)
from ironsbot.services.operations.request_feedback import request_feedback_scope
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
from ironsbot.services.seer.query_work import (
    record_cached_query_work,
    record_failed_query_work,
    record_rank_lookup_work,
    record_successful_query_work,
)
from ironsbot.services.seer.rank_models import (
    PeakSeasonRankSummary,
    PlayerRankSummary,
    RankLookupResult,
    RankSummaryProgress,
)
from ironsbot.services.seer.sequ_extra import (
    UnityPartOneInfo,
    UnityPeakInfo,
    fetch_unity_part_one,
    fetch_unity_peak_partial,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.local_rank import LocalRankService
    from ironsbot.services.seer.local_rank_metrics import MetricValue
    from ironsbot.services.seer.player_service import PlayerService
    from ironsbot.services.seer.player_service_models import PlayerBaseSnapshot
    from ironsbot.services.seer.rank import RankService

PlayerShortcutKind = Literal["collection", "peak", "autocard"]
logger = logging.getLogger(__name__)
_SHORTCUT_RE = re.compile(r"^(收集|巅峰|群星牌)(.*)$")
_KIND_BY_COMMAND: dict[str, PlayerShortcutKind] = {
    "收集": "collection",
    "巅峰": "peak",
    "群星牌": "autocard",
}
PLAYER_SHORTCUT_ACTIONS: dict[PlayerShortcutKind, ActionDefinition] = {
    "collection": ActionDefinition(
        "seer.player.collection",
        "收集与排行",
        cooldown_key="seer_player_collection",
    ),
    "peak": ActionDefinition(
        "seer.player.peak",
        "巅峰之战",
        cooldown_key="seer_player_peak",
    ),
    "autocard": ActionDefinition(
        "seer.player.autocard",
        "群星牌",
        cooldown_key="seer_player_autocard",
    ),
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
_PEAK_METRIC_KEYS_BY_MODE: dict[str, frozenset[str]] = {
    "standard": frozenset(
        ("peak_standard", "peak_standard_win_rate", "peak_standard_matches")
    ),
    "wild": frozenset(("peak_wild", "peak_wild_win_rate", "peak_wild_matches")),
    "expert": frozenset(
        ("peak_expert", "peak_expert_win_rate", "peak_expert_matches")
    ),
}


@dataclass(frozen=True, slots=True)
class PlayerShortcutCommand:
    kind: PlayerShortcutKind
    player_id: int | None
    player_reference: str | None = None
    base_snapshot: PlayerBaseSnapshot | None = None


@dataclass(frozen=True, slots=True)
class PlayerShortcutDependencies:
    rank: RankService
    local_rank: LocalRankService
    timeout_seconds: float = 30.0


PlayerShortcutStatusSender = Callable[[str], Awaitable[None]]


def _rank_summary_timeout_seconds(rank: RankService, fallback: float) -> float:
    """Let the cooperative rank scheduler finish its own bounded request cycle.

    The normal player-detail stage timeout is intentionally short.  Applying it
    to a multi-board lookup cancels the scheduler midway through a page, which
    turns unrelated boards into "not queried" results.  The scheduler already
    has a total budget and a per-page timeout; add one page as a small grace
    period so it can drain and return partial results itself.
    """

    player_lookup = getattr(getattr(rank, "config", None), "player_lookup", None)
    if player_lookup is None:
        return fallback
    try:
        return max(
            fallback,
            float(player_lookup.total_timeout_seconds)
            + float(player_lookup.page_timeout_seconds),
        )
    except (AttributeError, TypeError, ValueError):
        return fallback


def parse_player_shortcut_command(text: str) -> PlayerShortcutCommand | None:
    normalized = "".join(text.split())
    match = _SHORTCUT_RE.fullmatch(normalized)
    if match is None:
        return None
    command, player_reference = match.groups()
    player_reference = player_reference.strip()
    return PlayerShortcutCommand(
        kind=_KIND_BY_COMMAND[command],
        player_id=int(player_reference) if player_reference.isdecimal() else None,
        player_reference=(
            player_reference
            if player_reference and not player_reference.isdecimal()
            else None
        ),
    )


def player_request_admission_message(label: str, *, queued: bool) -> str:
    if queued:
        return f"⏳ 已收到：{label}，已加入队列，完成后会直接发送结果。"
    return f"⏳ {label}正在查询，完成后会直接发送结果。"


async def execute_player_shortcut(
    service: PlayerService,
    command: PlayerShortcutCommand,
    qq_user_id: int,
    *,
    group_id: int | None,
    send_status: PlayerShortcutStatusSender | None = None,
) -> QueryReply:
    """Run numeric-menu and text shortcuts through the same query path."""

    async def send_admission(label: str, *, queued: bool) -> None:
        if send_status is not None:
            await send_status(
                player_request_admission_message(label, queued=queued)
            )

    with request_feedback_scope(
        PLAYER_SHORTCUT_ACTIONS[command.kind].label,
        send_admission if send_status is not None else None,
    ):
        return await service.shortcut(
            command,
            qq_user_id,
            group_id=group_id,
        )


def player_shortcut_semantic_request(
    *,
    kind: PlayerShortcutKind,
    player_id: int,
    source: SemanticRequestSource,
) -> SemanticRequest:
    return SemanticRequest(
        action=PLAYER_SHORTCUT_ACTIONS[kind],
        target=SemanticTarget(
            key=str(player_id),
            display=f"米米号 {player_id}",
        ),
        source=source,
    )


async def fetch_player_shortcut_reply(
    dependencies: PlayerShortcutDependencies,
    game: Any,
    *,
    command: PlayerShortcutCommand,
    player_id: int,
    anchor_only: bool = False,
) -> QueryReply:
    if command.kind == "collection":
        text, rank_lookups = await _fetch_collection_message(
            dependencies.rank,
            dependencies.local_rank,
            game,
            player_id=player_id,
            base_snapshot=command.base_snapshot,
            timeout_seconds=dependencies.timeout_seconds,
            anchor_only=anchor_only,
        )
        _record_shortcut_rank_work("collection", rank_lookups)
        return QueryReply(
            text=text,
            rank_lookups=rank_lookups,
            complete=_is_complete_shortcut_reply(text, rank_lookups),
        )
    if command.kind == "peak":
        text, rank_lookups = await _fetch_peak_message(
            dependencies.rank,
            dependencies.local_rank,
            game,
            player_id=player_id,
            base_snapshot=command.base_snapshot,
            timeout_seconds=dependencies.timeout_seconds,
            anchor_only=anchor_only,
        )
        _record_shortcut_rank_work("peak", rank_lookups)
        return QueryReply(
            text=text,
            rank_lookups=rank_lookups,
            complete=_is_complete_shortcut_reply(text, rank_lookups),
        )
    text, rank_lookups = await _fetch_autocard_message(
        dependencies.rank,
        dependencies.local_rank,
        game,
        player_id=player_id,
        base_snapshot=command.base_snapshot,
        timeout_seconds=dependencies.timeout_seconds,
        anchor_only=anchor_only,
    )
    _record_shortcut_rank_work("autocard", rank_lookups)
    return QueryReply(
        text=text,
        rank_lookups=rank_lookups,
        complete=_is_complete_shortcut_reply(text, rank_lookups),
    )


async def _fetch_collection_message(  # noqa: PLR0913
    rank: RankService,
    local_rank: LocalRankService,
    game: Any,
    *,
    player_id: int,
    base_snapshot: PlayerBaseSnapshot | None,
    timeout_seconds: float,
    anchor_only: bool,
) -> tuple[str, tuple[RankLookupResult, ...]]:
    extra_errors: list[str] = []
    (nick, nick_error), more_info, unity_part_one = await asyncio.gather(
        _resolve_shortcut_nick(
            game,
            player_id=player_id,
            base_snapshot=base_snapshot,
            timeout_seconds=timeout_seconds,
        ),
        _resolve_collection_more_info(
            game,
            player_id=player_id,
            base_snapshot=base_snapshot,
            timeout_seconds=timeout_seconds,
            extra_errors=extra_errors,
        ),
        safe_player_extra(
            "图鉴基础数据",
            fetch_unity_part_one(game, player_id),
            None,
            extra_errors,
            on_error=_log_extra_error,
            timeout_seconds=timeout_seconds,
        ),
    )
    if any(error.startswith("图鉴基础数据") for error in extra_errors):
        record_failed_query_work("collection_unity")
    else:
        record_successful_query_work("collection_unity")
    rank_progress = RankSummaryProgress()
    rank_summary_fallback = PlayerRankSummary.empty()

    def record_rank_summary_error(label: str, error: Exception) -> None:
        _log_extra_error(label, error)
        rank_summary_fallback.mark_failure(
            label,
            format_player_extra_error(error),
        )

    rank_summary = await safe_player_extra(
        "全服排行",
        rank.fetch_player_summary(
            game,
            player_id,
            achieve_score=getattr(more_info, "total_achieve", None),
            pet_kind_count=int(getattr(unity_part_one, "pet_kind_num", 0) or 0),
            skin_score=int(getattr(unity_part_one, "skin_num", 0) or 0),
            progress=rank_progress,
            anchor_only=anchor_only,
        ),
        rank_summary_fallback,
        None,
        on_error=record_rank_summary_error,
        timeout_seconds=_rank_summary_timeout_seconds(rank, timeout_seconds),
        error_label_factory=lambda: rank_progress.current_title or "全服排行",
    )
    metrics = collect_metrics(
        more_info=more_info,
        unity_part_one=unity_part_one or UnityPartOneInfo(),
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
        timeout_seconds=timeout_seconds,
    )
    message = _append_extra_errors(
        format_collection_info(
            more_info,
            unity_part_one=unity_part_one,
            rank_summary=rank_summary,
            local_summary=local_summary,
            player_identity=format_player_identity(
                player_id,
                nick,
                nick_error,
            ),
        ),
        extra_errors,
    )
    return message, _player_rank_results(rank_summary)


async def _fetch_peak_message(  # noqa: PLR0913
    rank: RankService,
    local_rank: LocalRankService,
    game: Any,
    *,
    player_id: int,
    base_snapshot: PlayerBaseSnapshot | None,
    timeout_seconds: float,
    anchor_only: bool,
) -> tuple[str, tuple[RankLookupResult, ...]]:
    extra_errors: list[str] = []
    (nick, nick_error), peak_result = await asyncio.gather(
        _resolve_shortcut_nick(
            game,
            player_id=player_id,
            base_snapshot=base_snapshot,
            timeout_seconds=timeout_seconds,
        ),
        fetch_unity_peak_partial(
            game,
            player_id,
            timeout_seconds=timeout_seconds,
        ),
    )
    unity_peak = peak_result.info
    if peak_result.available_modes:
        record_successful_query_work("peak_base")
    else:
        record_failed_query_work("peak_base")
    for mode, error in peak_result.mode_errors:
        logger.warning("米米号详情字段获取失败：巅峰%s基础数据：%s", mode, error)
    peak_sub_key = rank.current_peak_sub_key()
    scores = calculate_player_peak_scores(
        unity_peak,
        available_modes=peak_result.available_modes,
    )
    peak_progress = RankSummaryProgress()
    peak_summary_fallback = PeakSeasonRankSummary.empty()

    def record_peak_summary_error(label: str, error: Exception) -> None:
        _log_extra_error(label, error)
        peak_summary_fallback.mark_failure(
            label,
            format_player_extra_error(error),
        )

    rank_summary = await safe_player_extra(
        "巅峰赛季榜",
        rank.fetch_peak_summary(
            game,
            player_id,
            standard_score=scores.standard,
            wild_score=scores.wild,
            expert_score=scores.expert,
            progress=peak_progress,
            anchor_only=anchor_only,
        ),
        peak_summary_fallback,
        None,
        on_error=record_peak_summary_error,
        timeout_seconds=_rank_summary_timeout_seconds(rank, timeout_seconds),
        error_label_factory=lambda: peak_progress.current_title or "巅峰赛季榜",
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
        timeout_seconds=timeout_seconds,
    )
    message = _append_extra_errors(
        format_compact_peak_section(
            unity_peak,
            rank_summary,
            local_summary,
            player_id=player_id,
            nick=nick,
            nick_error=nick_error,
            available_modes=peak_result.available_modes,
            mode_errors=dict(peak_result.mode_errors),
        ),
        extra_errors,
    )
    return message, (rank_summary.standard, rank_summary.wild, rank_summary.expert)


async def _fetch_autocard_message(  # noqa: PLR0913
    rank: RankService,
    local_rank: LocalRankService,
    game: Any,
    *,
    player_id: int,
    base_snapshot: PlayerBaseSnapshot | None,
    timeout_seconds: float,
    anchor_only: bool,
) -> tuple[str, tuple[RankLookupResult, ...]]:
    extra_errors: list[str] = []
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
            timeout_seconds=timeout_seconds,
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
            timeout_seconds=_rank_summary_timeout_seconds(rank, timeout_seconds),
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
        timeout_seconds=timeout_seconds,
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
        ),
        extra_errors,
    )
    return message, (result,)


async def _resolve_shortcut_nick(
    game: Any,
    *,
    player_id: int,
    base_snapshot: PlayerBaseSnapshot | None,
    timeout_seconds: float,
) -> tuple[str, str | None]:
    if base_snapshot is not None and base_snapshot.player_id == player_id:
        record_cached_query_work("profile")
        return base_snapshot.nick, None
    try:
        user_info = await asyncio.wait_for(
            game.get_user_info(player_id),
            timeout=timeout_seconds,
        )
    except Exception as error:  # noqa: BLE001
        _log_extra_error("玩家昵称", error)
        record_failed_query_work("profile")
        return "", format_player_extra_error(error)
    record_successful_query_work("profile")
    return str(getattr(user_info, "nick", "")), None


async def _resolve_collection_more_info(
    game: Any,
    *,
    player_id: int,
    base_snapshot: PlayerBaseSnapshot | None,
    timeout_seconds: float,
    extra_errors: list[str],
) -> Any:
    if (
        base_snapshot is not None
        and base_snapshot.player_id == player_id
        and _has_collection_more_info(base_snapshot.more_info)
    ):
        record_cached_query_work("profile_extra")
        return base_snapshot.more_info
    result = await safe_player_extra(
        "收集基础数据",
        game.get_more_user_info(player_id),
        None,
        extra_errors,
        on_error=_log_extra_error,
        timeout_seconds=timeout_seconds,
    )
    if any(error.startswith("收集基础数据") for error in extra_errors):
        record_failed_query_work("profile_extra")
    else:
        record_successful_query_work("profile_extra")
    return result


def _record_shortcut_rank_work(
    kind: PlayerShortcutKind,
    results: tuple[RankLookupResult, ...],
) -> None:
    keys = {
        "collection": (
            "book_score",
            "achievement_score",
            "pet_kind",
            "skin",
            "mintmark",
            "suit",
            "equip",
            "mount",
        ),
        "peak": ("peak_standard", "peak_wild", "peak_expert"),
        "autocard": ("autocard",),
    }[kind]
    for rank_key, result in zip(keys, results, strict=False):
        record_rank_lookup_work(rank_key, result)


def _is_complete_shortcut_reply(
    text: str,
    results: tuple[RankLookupResult, ...],
) -> bool:
    return (
        "⚠️ 部分数据查询失败" not in text
        and all(
            result.failure is None and not result.cost.restricted_miss
            for result in results
        )
    )


def _has_collection_more_info(value: Any) -> bool:
    return hasattr(value, "total_achieve") and hasattr(value, "pet_all_num")


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
