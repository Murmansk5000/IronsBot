# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ironsbot.services.seer.local_rank_formatting import format_metric_display
from ironsbot.services.seer.local_rank_models import LocalRankSummary
from ironsbot.services.seer.player_formatting_common import (
    format_player_identity,
    join_metric_parts,
)
from ironsbot.services.seer.player_query import calculate_player_peak_scores
from ironsbot.services.seer.rank_formatting import format_rank_position_text
from ironsbot.services.seer.rank_list_models import LOCAL_RANKS, RankPlayerCommand
from ironsbot.services.seer.rank_models import RankLookupResult
from ironsbot.services.seer.sequ_extra import fetch_unity_part_one, fetch_unity_peak

_PEAK_KEYS = frozenset(("竞技段位", "狂野段位", "专家段位"))

if TYPE_CHECKING:
    from ironsbot.services.seer.local_rank import LocalRankService
    from ironsbot.services.seer.rank import RankService


@dataclass(frozen=True, slots=True)
class RankPlayerScore:
    known: bool
    value: int | None


@dataclass(frozen=True, slots=True)
class RankPlayerQueryResult:
    message: str
    lookup: RankLookupResult


async def fetch_rank_player_result(
    rank: RankService,
    local_rank: LocalRankService,
    game: Any,
    *,
    command: RankPlayerCommand,
    anchor_only: bool = False,
) -> RankPlayerQueryResult:
    spec = rank.get_spec(command.rank_key)
    if rank.spec_needs_sub_key(spec):
        return RankPlayerQueryResult(
            "❌找不到当前巅峰赛季数据。",
            RankLookupResult(title="巅峰赛季榜", score_name="分"),
        )

    user_info = await game.get_user_info(command.player_id)
    target = await _fetch_player_score(game, command)
    result = await _find_player_rank(
        rank,
        game,
        command=command,
        target=target,
        key=spec.key,
        sub_key=spec.sub_key,
        title=spec.title,
        unit=spec.unit,
        anchor_only=anchor_only,
    )
    if (
        command.rank_key in _PEAK_KEYS
        and result.rank is None
        and result.queried
        and not result.cost.restricted_miss
    ):
        result = await rank.find_rank(
            game,
            user_id=command.player_id,
            title=spec.title.removesuffix("榜"),
            score_name=spec.unit,
            key=spec.key,
            sub_key=spec.sub_key,
            anchor_only=anchor_only,
        )

    score = (
        result.score
        if command.rank_key in _PEAK_KEYS
        else result.score
        if result.score is not None
        else target.value
    )
    if (
        command.rank_key not in _PEAK_KEYS
        and result.score is None
        and score is not None
    ):
        result.score = score

    metric_key = LOCAL_RANKS[command.rank_key].metric_key
    display = _format_score(metric_key, score, spec.unit)
    local_summary = await _update_sample_metric(
        local_rank,
        player_id=command.player_id,
        nick=str(user_info.nick),
        metric_key=metric_key,
        score=score,
        display=display,
        season_sub_key=spec.sub_key if command.rank_key in _PEAK_KEYS else None,
        clear_when_missing=command.rank_key in _PEAK_KEYS,
    )
    metric_text = join_metric_parts(
        display or "暂无数据",
        format_rank_position_text(result),
        local_summary.sample_rank(metric_key),
    )
    title = spec.title.removesuffix("榜")
    return RankPlayerQueryResult(
        "\n".join(
            (
                f"📊【{spec.title}玩家查询】",
                format_player_identity(command.player_id, str(user_info.nick)),
                f"{title}：{metric_text}",
            )
        ),
        result,
    )


async def fetch_rank_player_message(
    rank: RankService,
    local_rank: LocalRankService,
    game: Any,
    *,
    command: RankPlayerCommand,
    anchor_only: bool = False,
) -> str:
    """Return the stable text-only API used by existing callers."""

    return (
        await fetch_rank_player_result(
            rank,
            local_rank,
            game,
            command=command,
            anchor_only=anchor_only,
        )
    ).message


async def _fetch_player_score(
    game: Any,
    command: RankPlayerCommand,
) -> RankPlayerScore:
    rank_key = command.rank_key
    if rank_key == "成就点数":
        info = await game.get_more_user_info(command.player_id)
        return RankPlayerScore(
            known=True,
            value=int(getattr(info, "total_achieve", 0)) or None,
        )
    if rank_key in {"精灵图鉴", "皮肤图鉴"}:
        info = await fetch_unity_part_one(game, command.player_id)
        value = info.pet_kind_num if rank_key == "精灵图鉴" else info.skin_num
        return RankPlayerScore(known=True, value=int(value) or None)
    if rank_key in _PEAK_KEYS:
        info = await fetch_unity_peak(game, command.player_id)
        scores = calculate_player_peak_scores(info)
        values = {
            "竞技段位": scores.standard,
            "狂野段位": scores.wild,
            "专家段位": scores.expert,
        }
        return RankPlayerScore(known=True, value=values[rank_key])
    return RankPlayerScore(known=False, value=None)


async def _find_player_rank(  # noqa: PLR0913
    rank: RankService,
    game: Any,
    *,
    command: RankPlayerCommand,
    target: RankPlayerScore,
    key: int,
    sub_key: int,
    title: str,
    unit: str,
    anchor_only: bool,
) -> RankLookupResult:
    if target.known and target.value is None:
        return RankLookupResult(title=title, score_name=unit)
    if command.rank_key == "精灵图鉴" and target.value is not None:
        return await rank.find_pet_kind_rank(
            game,
            user_id=command.player_id,
            pet_kind_count=target.value,
            search_limit=None,
            anchor_only=anchor_only,
        )
    return await rank.find_rank(
        game,
        user_id=command.player_id,
        title=title.removesuffix("榜"),
        score_name=unit,
        key=key,
        sub_key=sub_key,
        target_score=target.value,
        anchor_only=anchor_only,
    )


def fetch_cached_rank_player_result(
    rank: RankService,
    *,
    command: RankPlayerCommand,
) -> RankPlayerQueryResult | None:
    """Format an existing rank fact or full-miss proof without live profile IO."""

    spec = rank.get_spec(command.rank_key)
    if rank.spec_needs_sub_key(spec):
        return None
    cached = rank.cached_player_lookup(
        rank_key=command.rank_key,
        user_id=command.player_id,
        title=spec.title.removesuffix("榜"),
        score_name=spec.unit,
        key=spec.key,
        sub_key=spec.sub_key,
    )
    if cached is None:
        return None
    cached_item, result = cached
    display = _format_score(
        LOCAL_RANKS[command.rank_key].metric_key,
        result.score,
        spec.unit,
    )
    metric_text = join_metric_parts(
        display or "暂无数据",
        format_rank_position_text(result),
    )
    identity = format_player_identity(
        command.player_id,
        "" if cached_item is None else str(cached_item.nick),
    )
    return RankPlayerQueryResult(
        "\n".join(
            (
                f"📊【{spec.title}玩家查询】",
                identity,
                f"{spec.title.removesuffix('榜')}：{metric_text}",
            )
        ),
        result,
    )


def _format_score(metric_key: str, score: int | None, unit: str) -> str:
    if score is None:
        return ""
    if metric_key in {"peak_standard", "peak_wild", "peak_expert"}:
        return format_metric_display(metric_key, score)
    return f"{score}{unit}"


async def _update_sample_metric(  # noqa: PLR0913
    local_rank: LocalRankService,
    *,
    player_id: int,
    nick: str,
    metric_key: str,
    score: int | None,
    display: str,
    season_sub_key: int | None,
    clear_when_missing: bool = False,
) -> LocalRankSummary:
    if not local_rank.config.enabled:
        return LocalRankSummary()
    clear_metric_keys = (
        frozenset((metric_key,))
        if clear_when_missing and score is None
        else frozenset()
    )
    if score is None and not clear_metric_keys:
        return LocalRankSummary()
    return await local_rank.upsert_metrics(
        player_id=player_id,
        nick=nick,
        current_metrics=(
            {
                metric_key: {
                    "value": score,
                    "season_sub_key": season_sub_key,
                    "display": display or None,
                }
            }
            if score is not None
            else {}
        ),
        peak_sub_key=season_sub_key,
        clear_metric_keys=clear_metric_keys,
    )
