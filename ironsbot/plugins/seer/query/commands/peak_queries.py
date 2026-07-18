# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: TC001, TC002
"""Peak query matchers."""

from __future__ import annotations

from functools import partial
from typing import Annotated

from nonebot.matcher import Matcher
from nonebot.params import Depends, Fullmatch
from seerapi_models import PeakExpertPoolORM

from ironsbot.integrations.headless_seer.game import SeerGame
from ironsbot.integrations.seer_data.sessions import AllSessions
from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.utils.rule import no_reply

from ..depends import SeerAPISession, game_client_dependency
from ..group import SeerMatcherGroup, seer_feature_rule
from . import peak_handlers


def install(group: SeerMatcherGroup) -> None:
    game_client = game_client_dependency(group.resources.headless)

    async def handle_peak_vote(
        matcher: Matcher,
        session: SeerAPISession,
        game: SeerGame = game_client,
    ) -> None:
        await peak_handlers.handle_peak_vote(
            matcher=matcher,
            session=session,
            game=game,
        )

    async def handle_peak_suit(
        matcher: Matcher,
        seerapi_session: SeerAPISession,
        sessions: AllSessions,
        type_selection: peak_handlers.PeakTypeSelection = Depends(
            peak_handlers.get_peak_type
        ),
        game: SeerGame = game_client,
    ) -> None:
        await peak_handlers.handle_peak_suit(
            matcher=matcher,
            seerapi_session=seerapi_session,
            sessions=sessions,
            type_selection=type_selection,
            game=game,
        )

    async def handle_peak_title(
        matcher: Matcher,
        seerapi_session: SeerAPISession,
        sessions: AllSessions,
        type_selection: peak_handlers.PeakTypeSelection = Depends(
            peak_handlers.get_peak_type
        ),
        game: SeerGame = game_client,
    ) -> None:
        await peak_handlers.handle_title(
            matcher=matcher,
            seerapi_session=seerapi_session,
            sessions=sessions,
            type_selection=type_selection,
            game=game,
        )

    async def handle_peak_pet(  # noqa: PLR0913
        matcher: Matcher,
        seerapi_session: SeerAPISession,
        command: Annotated[str, Fullmatch()],
        type_selection: peak_handlers.PeakTypeSelection = Depends(
            peak_handlers.get_peak_type
        ),
        expert_pools: list[PeakExpertPoolORM] = Depends(
            peak_handlers.get_expert_ban_pool
        ),
        game: SeerGame = game_client,
    ) -> None:
        await peak_handlers.handle_peak_pet(
            matcher=matcher,
            seerapi_session=seerapi_session,
            command=command,
            type_selection=type_selection,
            expert_pools=expert_pools,
            game=game,
        )

    rule = seer_feature_rule(group.resources.features, "seer_peak") & no_reply()
    priority = group.matcher_priority("seer_peak")

    pool = group.on_fullmatch(
        ("竞技池", "巅峰竞技池", "竞技精灵池", "限制池"),
        policy=CommandPolicy.command("seer_peak_pool"),
        rule=rule,
        priority=priority,
    )
    pool.append_handler(
        partial(peak_handlers.handle_peak_pool, group.resources.render_cache)
    )

    expert_pool = group.on_fullmatch(
        ("专家池", "巅峰专家池", "专家禁用池"),
        policy=CommandPolicy.command("seer_peak_expert_pool"),
        rule=rule,
        priority=priority,
    )
    expert_pool.append_handler(
        partial(peak_handlers.handle_peak_expert_pool, group.resources.render_cache)
    )

    vote = group.on_fullmatch(
        ("巅峰投票", "巅峰票选", "巅峰池票选", "竞技池票选", "限制池票选"),
        policy=CommandPolicy.command("seer_peak_vote"),
        rule=rule,
        priority=priority,
    )
    vote.append_handler(handle_peak_vote)

    suit = group.on_fullmatch(
        ("竞技套装榜", "狂野套装榜", "专家套装榜"),
        policy=CommandPolicy.command("seer_peak_suit_rank"),
        rule=rule,
        priority=priority,
    )
    suit.append_handler(handle_peak_suit)

    title = group.on_fullmatch(
        ("竞技称号榜", "狂野称号榜", "专家称号榜"),
        policy=CommandPolicy.command("seer_peak_title_rank"),
        rule=rule,
        priority=priority,
    )
    title.append_handler(handle_peak_title)

    pet = group.on_fullmatch(
        (
            "竞技精灵月榜",
            "狂野精灵月榜",
            "专家精灵月榜",
            "竞技精灵总榜",
            "狂野精灵总榜",
            "专家精灵总榜",
        ),
        policy=CommandPolicy.command("seer_peak_pet_rank"),
        rule=rule,
        priority=priority,
    )
    pet.append_handler(handle_peak_pet)
