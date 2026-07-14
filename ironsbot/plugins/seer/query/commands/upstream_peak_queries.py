# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: TC001, TC002
"""Upstream peak query matchers."""

from __future__ import annotations

from typing import Annotated

from nonebot.matcher import Matcher
from nonebot.params import Depends, Fullmatch

from ironsbot.utils.rule import no_reply

from ..depends import SeerAPISession
from ..group import matcher_group, seer_feature_priority, seer_feature_rule
from ..upstream_commands import peak as upstream_peak

peak_pool_matcher = matcher_group.on_fullmatch(
    ("竞技池", "巅峰竞技池", "竞技精灵池", "限制池"),
    rule=seer_feature_rule("seer_peak") & no_reply(),
    priority=seer_feature_priority("seer_peak"),
)


@peak_pool_matcher.handle()
async def _handle_peak_pool(
    matcher: Matcher,
    pools: list[upstream_peak.PeakPoolORM] = Depends(
        upstream_peak._get_standard_limit_pool
    ),
) -> None:
    await upstream_peak.handle_peak_pool(
        matcher=matcher,
        pools=pools,
    )
peak_expert_pool_matcher = matcher_group.on_fullmatch(
    ("专家池", "巅峰专家池", "专家禁用池"),
    rule=seer_feature_rule("seer_peak") & no_reply(),
    priority=seer_feature_priority("seer_peak"),
)


@peak_expert_pool_matcher.handle()
async def _handle_peak_expert_pool(
    matcher: Matcher,
    pools: list[upstream_peak.PeakExpertPoolORM] = Depends(
        upstream_peak._get_expert_ban_pool
    ),
) -> None:
    await upstream_peak.handle_peak_expert_pool(
        matcher=matcher,
        pools=pools,
    )
peak_vote_matcher = matcher_group.on_fullmatch(
    ("巅峰投票", "巅峰票选", "巅峰池票选", "竞技池票选", "限制池票选"),
    rule=seer_feature_rule("seer_peak") & no_reply(),
    priority=seer_feature_priority("seer_peak"),
)


@peak_vote_matcher.handle()
async def _handle_peak_vote(
    matcher: Matcher,
    session: SeerAPISession,
    game: upstream_peak.SeerGame = upstream_peak.GameClient,
) -> None:
    await upstream_peak.handle_peak_vote(
        matcher=matcher,
        session=session,
        game=game,
    )

peak_suit_matcher = matcher_group.on_fullmatch(
    ("竞技套装榜", "狂野套装榜", "专家套装榜"),
    rule=seer_feature_rule("seer_peak") & no_reply(),
    priority=seer_feature_priority("seer_peak"),
)


@peak_suit_matcher.handle()
async def _handle_peak_suit(
    matcher: Matcher,
    seerapi_session: SeerAPISession,
    sessions: upstream_peak.AllSessions,
    type_tuple: upstream_peak._PeakTypeTuple = Depends(upstream_peak._get_peak_type),
    game: upstream_peak.SeerGame = upstream_peak.GameClient,
) -> None:
    await upstream_peak.handle_peak_suit(
        matcher=matcher,
        seerapi_session=seerapi_session,
        sessions=sessions,
        type_tuple=type_tuple,
        game=game,
    )

peak_title_matcher = matcher_group.on_fullmatch(
    ("竞技称号榜", "狂野称号榜", "专家称号榜"),
    rule=seer_feature_rule("seer_peak") & no_reply(),
    priority=seer_feature_priority("seer_peak"),
)


@peak_title_matcher.handle()
async def _handle_peak_title(
    matcher: Matcher,
    seerapi_session: SeerAPISession,
    sessions: upstream_peak.AllSessions,
    type_tuple: upstream_peak._PeakTypeTuple = Depends(upstream_peak._get_peak_type),
    game: upstream_peak.SeerGame = upstream_peak.GameClient,
) -> None:
    await upstream_peak.handle_title(
        matcher=matcher,
        seerapi_session=seerapi_session,
        sessions=sessions,
        type_tuple=type_tuple,
        game=game,
    )

peak_pet_matcher = matcher_group.on_fullmatch(
    (
        "竞技精灵月榜",
        "狂野精灵月榜",
        "专家精灵月榜",
        "竞技精灵总榜",
        "狂野精灵总榜",
        "专家精灵总榜",
    ),
    rule=seer_feature_rule("seer_peak") & no_reply(),
    priority=seer_feature_priority("seer_peak"),
)


@peak_pet_matcher.handle()
async def _handle_peak_pet(  # noqa: PLR0913
    matcher: Matcher,
    seerapi_session: SeerAPISession,
    command: Annotated[str, Fullmatch()],
    type_tuple: upstream_peak._PeakTypeTuple = Depends(upstream_peak._get_peak_type),
    expert_pools: list[upstream_peak.PeakExpertPoolORM] = Depends(
        upstream_peak._get_expert_ban_pool
    ),
    game: upstream_peak.SeerGame = upstream_peak.GameClient,
) -> None:
    await upstream_peak.handle_peak_pet(
        matcher=matcher,
        seerapi_session=seerapi_session,
        command=command,
        type_tuple=type_tuple,
        expert_pools=expert_pools,
        game=game,
    )
