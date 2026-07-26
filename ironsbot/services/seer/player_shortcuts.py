# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
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
from ironsbot.services.seer.sequ_extra import (
    UnityPartOneInfo,
    UnityPeakInfo,
    fetch_unity_part_one,
    fetch_unity_peak,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.local_rank import LocalRankService
    from ironsbot.services.seer.local_rank_metrics import MetricValue
    from ironsbot.services.seer.rank import RankService

PlayerShortcutKind = Literal["collection", "peak", "autocard"]
logger = logging.getLogger(__name__)
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


@dataclass(frozen=True, slots=True)
class PlayerShortcutDependencies:
    rank: RankService
    local_rank: LocalRankService
    timeout_seconds: float = 30.0


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


async def fetch_player_shortcut_reply(
    dependencies: PlayerShortcutDependencies,
    game: Any,
    *,
    command: PlayerShortcutCommand,
    player_id: int,
) -> QueryReply:
    if command.kind == "collection":
        return QueryReply(
            text=await _fetch_collection_message(
                dependencies.rank,
                dependencies.local_rank,
                game,
                player_id=player_id,
                timeout_seconds=dependencies.timeout_seconds,
            )
        )
    if command.kind == "peak":
        return QueryReply(
            text=await _fetch_peak_message(
                dependencies.rank,
                dependencies.local_rank,
                game,
                player_id=player_id,
                timeout_seconds=dependencies.timeout_seconds,
            )
        )
    return QueryReply(
        text=await _fetch_autocard_message(
            dependencies.rank,
            dependencies.local_rank,
            game,
            player_id=player_id,
            timeout_seconds=dependencies.timeout_seconds,
        )
    )


async def _fetch_collection_message(
    rank: RankService,
    local_rank: LocalRankService,
    game: Any,
    *,
    player_id: int,
    timeout_seconds: float,
) -> str:
    extra_errors: list[str] = []
    user_info, more_info, unity_part_one = await asyncio.gather(
        safe_player_extra(
            "玩家昵称",
            game.get_user_info(player_id),
            SimpleNamespace(nick=""),
            extra_errors,
            on_error=_log_extra_error,
            timeout_seconds=timeout_seconds,
        ),
        safe_player_extra(
            "收集基础数据",
            game.get_more_user_info(player_id),
            SimpleNamespace(total_achieve=0, pet_all_num=0),
            extra_errors,
            on_error=_log_extra_error,
            timeout_seconds=timeout_seconds,
        ),
        safe_player_extra(
            "图鉴基础数据",
            fetch_unity_part_one(game, player_id),
            UnityPartOneInfo(),
            extra_errors,
            on_error=_log_extra_error,
            timeout_seconds=timeout_seconds,
        ),
    )
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
            pet_kind_count=unity_part_one.pet_kind_num,
            skin_score=unity_part_one.skin_num,
            progress=rank_progress,
        ),
        rank_summary_fallback,
        None,
        on_error=record_rank_summary_error,
        timeout_seconds=timeout_seconds,
        error_label_factory=lambda: rank_progress.current_title or "全服排行",
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
            nick=str(user_info.nick),
            metrics=metrics,
            allowed_keys=_COLLECTION_METRIC_KEYS,
            peak_sub_key=None,
        ),
        LocalRankSummary(),
        extra_errors,
        on_error=_log_extra_error,
        timeout_seconds=timeout_seconds,
    )
    return _append_extra_errors(
        format_collection_info(
            more_info,
            unity_part_one=unity_part_one,
            rank_summary=rank_summary,
            local_summary=local_summary,
            player_identity=format_player_identity(player_id, user_info.nick),
        ),
        extra_errors,
    )


async def _fetch_peak_message(
    rank: RankService,
    local_rank: LocalRankService,
    game: Any,
    *,
    player_id: int,
    timeout_seconds: float,
) -> str:
    extra_errors: list[str] = []
    user_info, unity_peak = await asyncio.gather(
        safe_player_extra(
            "玩家昵称",
            game.get_user_info(player_id),
            SimpleNamespace(nick=""),
            extra_errors,
            on_error=_log_extra_error,
            timeout_seconds=timeout_seconds,
        ),
        safe_player_extra(
            "巅峰基础数据",
            fetch_unity_peak(game, player_id),
            UnityPeakInfo(),
            extra_errors,
            on_error=_log_extra_error,
            timeout_seconds=timeout_seconds,
        ),
    )
    peak_sub_key = rank.current_peak_sub_key()
    scores = calculate_player_peak_scores(unity_peak)
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
        ),
        peak_summary_fallback,
        None,
        on_error=record_peak_summary_error,
        timeout_seconds=timeout_seconds,
        error_label_factory=lambda: peak_progress.current_title or "巅峰赛季榜",
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
    local_summary = await safe_player_extra(
        "样本数据",
        _update_selected_metrics(
            local_rank,
            player_id=player_id,
            nick=str(user_info.nick),
            metrics=metrics,
            allowed_keys=_PEAK_METRIC_KEYS,
            peak_sub_key=peak_sub_key,
            clear_metric_keys=validated_peak.clear_metric_keys,
        ),
        LocalRankSummary(),
        extra_errors,
        on_error=_log_extra_error,
        timeout_seconds=timeout_seconds,
    )
    return _append_extra_errors(
        format_compact_peak_section(
            unity_peak,
            rank_summary,
            local_summary,
            player_id=player_id,
            nick=str(user_info.nick),
        ),
        extra_errors,
    )


async def _fetch_autocard_message(
    rank: RankService,
    local_rank: LocalRankService,
    game: Any,
    *,
    player_id: int,
    timeout_seconds: float,
) -> str:
    extra_errors: list[str] = []
    autocard_fallback = RankLookupResult(
        title="群星之巅榜",
        score_name="分",
    )

    def record_autocard_error(label: str, error: Exception) -> None:
        _log_extra_error(label, error)
        autocard_fallback.failure = format_player_extra_error(error)

    user_info, result = await asyncio.gather(
        safe_player_extra(
            "玩家昵称",
            game.get_user_info(player_id),
            SimpleNamespace(nick=""),
            extra_errors,
            on_error=_log_extra_error,
            timeout_seconds=timeout_seconds,
        ),
        safe_player_extra(
            "群星牌排行",
            rank.fetch_autocard_summary(game, player_id),
            autocard_fallback,
            None,
            on_error=record_autocard_error,
            timeout_seconds=timeout_seconds,
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
            nick=str(user_info.nick),
            metrics=metrics,
            allowed_keys=frozenset(("autocard_score",)),
            peak_sub_key=None,
        ),
        LocalRankSummary(),
        extra_errors,
        on_error=_log_extra_error,
        timeout_seconds=timeout_seconds,
    )
    return _append_extra_errors(
        format_autocard_rank_info(
            result,
            player_identity=format_player_identity(player_id, user_info.nick),
            local_summary=local_summary,
        ),
        extra_errors,
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
