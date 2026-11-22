# SPDX-License-Identifier: MIT
"""Read-only Somua detail observations shared by all player entrypoints."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from ironsbot.core.time import ObservationTime
from ironsbot.services.seer.player_formatting_common import format_player_data_time
from ironsbot.services.seer.query_result import QueryReply
from ironsbot.services.seer.query_work import QueryWorkResult
from ironsbot.services.seer.somua_codec import parse_somua_detail
from ironsbot.services.seer.somua_models import SomuaDetail, SomuaParent, SomuaParts

if TYPE_CHECKING:
    from ironsbot.services.seer.observation_cache import ObservationCache
    from ironsbot.services.seer.player_shortcut_contracts import (
        PlayerShortcutDependencies,
    )


_UINT32_MAX = 0xFFFFFFFF


@dataclass(frozen=True, slots=True)
class SomuaDetailObservation:
    detail: SomuaDetail
    fetched_at: float
    cached: bool


def _identity(player_id: int, sequence: int) -> tuple[int, str]:
    return player_id, f"somua_detail:{sequence}"


def cached_detail_reply(
    cache: ObservationCache | None, ttl: float, player_id: int, sequence: int
) -> QueryReply | None:
    item = None if cache is None else cache.get(_identity(player_id, sequence), ttl)
    if item is None or not isinstance(item.value, SomuaDetail):
        return None
    if item.value.player_id != player_id or item.value.sequence != sequence:
        return None
    return _reply(item.value, item.fetched_at, cached=True)


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
    return _reply(item.detail, item.fetched_at, cached=item.cached)


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


def _parts(parts: SomuaParts) -> str:
    labels = ("身体", "表情", "手", "耳", "尾", "头", "上装", "背部", "环绕")
    return "、".join(
        f"{label} {value}"
        for label, value in zip(labels, asdict(parts).values(), strict=True)
    )


def _parent(label: str, parent: SomuaParent) -> str:
    return (
        f"{label}：{parent.name or '名称未提供'}｜代数 {parent.generation}｜"
        f"主人 {parent.owner_name or '未提供'}\n"
        f"创建时间戳：{parent.created_at}\n外观：{_parts(parent.parts)}"
    )


def _reply(detail: SomuaDetail, fetched_at: float, *, cached: bool) -> QueryReply:
    unit = f"somua_detail:{detail.sequence}"
    return QueryReply(
        text="\n".join(
            (
                "【苏摩详情】",
                format_player_data_time(fetched_at),
                f"米米号：{detail.player_id}",
                f"名称：{detail.name or '未提供'}｜实例：{detail.sequence}",
                f"代数：{detail.generation}｜形态编号：{detail.form_id}｜成长阶段编号：{detail.stage}",
                f"基因编号（客户端顺序）：{'、'.join(map(str, detail.genes))}",
                f"性格编号：{detail.personality}｜攻击模式编号：{detail.attack_mode}",
                f"能力参数（客户端顺序）：{'、'.join(map(str, detail.attributes))}",
                f"外观：{_parts(detail.parts)}",
                f"装备成就编号：{detail.achievement_id}｜收藏标记：{detail.is_collected}",
                f"位置编号：{detail.location}｜出战标记：{detail.match_flag}",
                f"创建时间戳：{detail.created_at}｜上次互动时间戳：{detail.last_touch_at}",
                _parent("父系", detail.father),
                _parent("母系", detail.mother),
            )
        ),
        fetched_at=fetched_at,
        query_work=QueryWorkResult(
            scope="foreground",
            successful_units=frozenset() if cached else frozenset({unit}),
            cached_units=frozenset({unit}) if cached else frozenset(),
        ),
    )
