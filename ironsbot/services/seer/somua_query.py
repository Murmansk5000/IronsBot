# SPDX-License-Identifier: MIT
"""Public player shortcut for Somua; no self-only battle-history requests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any

from ironsbot.core.time import ObservationTime
from ironsbot.services.seer.player_formatting_common import (
    format_player_data_time,
    format_player_identity,
)
from ironsbot.services.seer.player_query import format_player_extra_error
from ironsbot.services.seer.player_shortcut_queries import (
    _observe_detail,
    _resolve_shortcut_nick,
)
from ironsbot.services.seer.query_work import QueryWorkResult
from ironsbot.services.seer.rank_models import RankLookupResult
from ironsbot.services.seer.somua import SOMUA_SCORE_PARAM
from ironsbot.services.seer.somua_detail import fetch_somua_detail_observation
from ironsbot.services.seer.somua_models import SomuaOverviewReply

_UINT32_MAX = 0xFFFFFFFF

if TYPE_CHECKING:
    from ironsbot.core.tasks import OperationDeadline
    from ironsbot.services.seer.player_shortcut_contracts import (
        PlayerShortcutCommand,
        PlayerShortcutDependencies,
    )
    from ironsbot.services.seer.query_result import QueryReply


async def fetch_somua_reply(  # noqa: PLR0913 - shared shortcut execution context
    dependencies: PlayerShortcutDependencies,
    game: Any,
    *,
    command: PlayerShortcutCommand,
    player_id: int,
    deadline: OperationDeadline,
    anchor_only: bool,
) -> QueryReply:
    observation = ObservationTime()
    successful: set[str] = set()
    cached: set[str] = set()
    failed: set[str] = set()
    errors: list[str] = []
    score: int | None = None
    cache = dependencies.observations
    identity = (player_id, "somua_score")
    ttl = dependencies.observation_ttl

    async def score_result() -> None:
        nonlocal score
        try:
            if anchor_only:
                item = None if cache is None else cache.get(identity, ttl)
                if item is not None:
                    score = item.value
                    observation.include(item.fetched_at)
            else:
                async with asyncio.timeout(
                    deadline.remaining(dependencies.timeout_seconds)
                ):
                    score = await _observe_detail(
                        cache,
                        identity,
                        partial(_read_score, game, player_id, successful),
                        observation=observation,
                        ttl=ttl,
                    )
            if score is not None and "somua_score" not in successful:
                cached.add("somua_score")
        except Exception as error:  # noqa: BLE001 - independent score failure
            failed.add("somua_score")
            errors.append(f"积分查询失败：{format_player_extra_error(error)}")

    _, (nick, nick_error) = await asyncio.gather(
        score_result(),
        _resolve_shortcut_nick(
            game,
            player_id=player_id,
            base_snapshot=command.base_snapshot,
            timeout_seconds=deadline.remaining(dependencies.timeout_seconds),
            observation=observation,
            observations=cache,
            observation_ttl=ttl,
        ),
    )
    result = RankLookupResult(title="苏摩全服榜", score_name="分")
    try:
        async with asyncio.timeout(
            deadline.remaining(dependencies.rank_timeout_seconds)
        ):
            result = await dependencies.rank.fetch_somua_summary(
                game, player_id, score=score, anchor_only=anchor_only
            )
        if (
            score is not None
            and result.rank is not None
            and (
                result.score != score
                or (
                    result.observed_score is not None and result.observed_score != score
                )
            )
        ):
            result.rank = None
            result.failure = "积分与榜单数据不一致，暂时无法确认排名。"
            result.common_somua = None
            result.common_failure = result.failure
        if result.failure or result.cost.restricted_miss or not result.queried:
            failed.add("rank:somua")
        else:
            observation.include(result.fetched_at)
            if (
                result.cost.online_page_fetches
                and not result.cost.lightweight_confirmed
            ):
                successful.add("rank:somua")
            else:
                cached.add("rank:somua")
    except Exception as error:  # noqa: BLE001 - preserve independent score result
        result.failure = format_player_extra_error(error)
        failed.add("rank:somua")

    _include_common_result(result, observation, errors)
    names = await _fetch_common_names(
        dependencies,
        game,
        player_id=player_id,
        result=result,
        deadline=deadline,
        anchor_only=anchor_only,
        observation=observation,
    )
    errors.extend(names.errors)
    return SomuaOverviewReply(
        text=_format_somua_reply(
            score,
            result,
            (
                format_player_data_time(observation.fetched_at),
                format_player_identity(player_id, nick, nick_error),
            ),
            errors,
        ),
        rank_lookups=(result,),
        fetched_at=observation.fetched_at,
        common_somua=result.common_somua,
        common_fetched_at=result.common_fetched_at,
        common_names=names.names,
        complete=(
            score is not None
            and not failed
            and nick_error is None
            and result.common_somua is not None
            and not names.errors
        ),
        query_work=QueryWorkResult(
            scope="foreground",
            successful_units=frozenset(successful) | names.work.successful_units,
            failed_units=frozenset(failed) | names.work.failed_units,
            cached_units=frozenset(cached) | names.work.cached_units,
        ),
    )


@dataclass(frozen=True, slots=True)
class _CommonNames:
    names: tuple[tuple[int, str], ...]
    work: QueryWorkResult
    errors: tuple[str, ...]


async def _fetch_common_names(  # noqa: PLR0913 - shared query budget and target
    dependencies: PlayerShortcutDependencies,
    game: Any,
    *,
    player_id: int,
    result: RankLookupResult,
    deadline: OperationDeadline,
    anchor_only: bool,
    observation: ObservationTime,
) -> _CommonNames:
    successful: set[str] = set()
    cached: set[str] = set()
    failed: set[str] = set()
    names: list[tuple[int, str]] = []
    missing_names = False
    sequences = dict.fromkeys(
        slot.sequence for slot in (result.common_somua or ())[:3] if slot.sequence
    )
    for sequence in sequences:
        unit = f"somua_detail:{sequence}"
        try:
            remaining = deadline.remaining(dependencies.timeout_seconds)
            async with asyncio.timeout(remaining):
                item = await fetch_somua_detail_observation(
                    dependencies,
                    game,
                    player_id=player_id,
                    sequence=sequence,
                    anchor_only=anchor_only or remaining <= 0,
                )
            if item is None:
                missing_names = True
                continue
            (cached if item.cached else successful).add(unit)
            observation.include(item.fetched_at)
            name = " ".join(item.detail.name.split())
            if name:
                names.append((sequence, name))
            else:
                missing_names = True
        except Exception:  # noqa: BLE001 - optional names preserve score and choices
            missing_names = True
            failed.add(unit)
    return _CommonNames(
        names=tuple(names),
        errors=("部分苏摩名称暂不可用，仍可选择编号查看详情。",)
        if missing_names
        else (),
        work=QueryWorkResult(
            scope="foreground",
            successful_units=frozenset(successful),
            failed_units=frozenset(failed),
            cached_units=frozenset(cached),
        ),
    )


async def _read_score(game: Any, player_id: int, successful: set[str]) -> int:
    _head, body = await game.send_and_wait(40002, player_id, SOMUA_SCORE_PARAM)
    value = int(body.value)
    if not 0 <= value <= _UINT32_MAX:
        raise ValueError("苏摩积分数据异常")
    successful.add("somua_score")
    return value


def _include_common_result(
    result: RankLookupResult, observation: ObservationTime, errors: list[str]
) -> None:
    if result.common_fetched_at is not None:
        observation.include(result.common_fetched_at)
    if result.common_failure:
        errors.append(f"常用苏摩：暂无法获取（{result.common_failure}）")
    elif result.common_somua is None:
        errors.append("常用苏摩：榜单未提供数据，暂无法获取")
    elif not any(slot.sequence for slot in result.common_somua):
        errors.append("常用苏摩：暂无可展示的实例")


def _format_somua_reply(
    score: int | None,
    result: RankLookupResult,
    header: tuple[str, str],
    errors: list[str],
) -> str:
    score_text = f"积分：{score}" if score is not None else "积分：暂无法获取"
    if (
        score is None
        and result.rank is not None
        and result.score is not None
        and not result.failure
    ):
        score_text = f"积分：{result.score}（榜单记录）"
    lines = [
        "【苏摩竞技场】",
        *header,
        score_text,
    ]
    if result.failure or result.cost.restricted_miss or not result.queried:
        reason = result.failure or "搜索范围或预算受限"
        lines.append(f"全服排名：暂无法确认（{reason}）")
    elif result.rank is not None:
        lines.append(f"全服排名：第{result.rank}名")
    else:
        lines.append(f"全服排名：未进入已确认的前{result.searched_limit}名")
    lines.extend(errors)
    return "\n".join(lines)
