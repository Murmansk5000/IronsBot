# SPDX-License-Identifier: MIT
"""Read-only Somua detail observations shared by all player entrypoints."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ironsbot.core.time import ObservationTime
from ironsbot.services.seer.player_formatting_common import format_player_data_time
from ironsbot.services.seer.query_result import QueryReply
from ironsbot.services.seer.query_work import QueryWorkResult
from ironsbot.services.seer.somua_codec import parse_somua_detail
from ironsbot.services.seer.somua_models import SomuaDetail
from ironsbot.services.seer.somua_presentation import (
    SomuaTextSnapshot,
    format_somua_detail,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.observation_cache import ObservationCache
    from ironsbot.services.seer.player_shortcut_contracts import (
        PlayerShortcutDependencies,
    )
    from ironsbot.services.seer.somua_presentation import SomuaTextResolver


_UINT32_MAX = 0xFFFFFFFF


@dataclass(frozen=True, slots=True)
class SomuaDetailObservation:
    detail: SomuaDetail
    fetched_at: float
    cached: bool


def _identity(player_id: int, sequence: int) -> tuple[int, str]:
    return player_id, f"somua_detail:{sequence}"


def cached_detail_reply(
    cache: ObservationCache | None,
    ttl: float,
    player_id: int,
    sequence: int,
    *,
    text_resolver: SomuaTextResolver | None = None,
) -> QueryReply | None:
    item = None if cache is None else cache.get(_identity(player_id, sequence), ttl)
    if item is None or not isinstance(item.value, SomuaDetail):
        return None
    if item.value.player_id != player_id or item.value.sequence != sequence:
        return None
    return _reply(item.value, item.fetched_at, cached=True, text_resolver=text_resolver)


async def fetch_somua_detail_reply(
    dependencies: PlayerShortcutDependencies,
    game: Any,
    *,
    player_id: int,
    sequence: int,
    anchor_only: bool,
) -> QueryReply:
    item = await fetch_somua_detail_observation(
        dependencies,
        game,
        player_id=player_id,
        sequence=sequence,
        anchor_only=anchor_only,
    )
    if item is None:
        return QueryReply(
            text="苏摩详情暂无有效缓存，当前查询额度不允许联网查询。", complete=False
        )
    return _reply(
        item.detail,
        item.fetched_at,
        cached=item.cached,
        text_resolver=dependencies.somua_text,
    )


async def fetch_somua_detail_observation(
    dependencies: PlayerShortcutDependencies,
    game: Any,
    *,
    player_id: int,
    sequence: int,
    anchor_only: bool,
) -> SomuaDetailObservation | None:
    if not 0 < sequence <= _UINT32_MAX:
        raise ValueError("苏摩实例编号无效")
    cache = dependencies.observations
    cached = (
        None
        if cache is None
        else cache.get(_identity(player_id, sequence), dependencies.observation_ttl)
    )
    if (
        cached is not None
        and isinstance(cached.value, SomuaDetail)
        and cached.value.player_id == player_id
        and cached.value.sequence == sequence
    ):
        return SomuaDetailObservation(cached.value, cached.fetched_at, cached=True)
    if cached is not None:
        assert cache is not None
        cache.discard(_identity(player_id, sequence))
    if anchor_only:
        return None
    observation = ObservationTime()
    loaded = False

    async def fetch() -> SomuaDetail:
        nonlocal loaded
        async with asyncio.timeout(dependencies.timeout_seconds):
            _head, body = await game.send_and_wait(45969, player_id, sequence)
        detail = parse_somua_detail(bytes(body), player_id=player_id, sequence=sequence)
        loaded = True
        return detail

    if dependencies.observations is None:
        detail = await fetch()
        from ironsbot.core.time import now

        observation.include(now().timestamp())
    else:
        detail = await dependencies.observations.observe(
            _identity(player_id, sequence),
            fetch,
            ttl=dependencies.observation_ttl,
            observation=observation,
        )
    assert observation.fetched_at is not None
    if detail.player_id != player_id or detail.sequence != sequence:
        raise ValueError("苏摩详情身份不一致")
    return SomuaDetailObservation(detail, observation.fetched_at, not loaded)


def _reply(
    detail: SomuaDetail,
    fetched_at: float,
    *,
    cached: bool,
    text_resolver: SomuaTextResolver | None,
) -> QueryReply:
    unit = f"somua_detail:{detail.sequence}"
    snapshot = (
        SomuaTextSnapshot(unavailable=("资料配置",))
        if text_resolver is None
        else text_resolver.resolve(detail)
    )
    return QueryReply(
        text="\n".join(
            (
                "【苏摩详情】",
                format_player_data_time(fetched_at),
                format_somua_detail(detail, snapshot),
            )
        ),
        fetched_at=fetched_at,
        query_work=QueryWorkResult(
            scope="foreground",
            successful_units=frozenset() if cached else frozenset({unit}),
            cached_units=frozenset({unit}) if cached else frozenset(),
        ),
    )
