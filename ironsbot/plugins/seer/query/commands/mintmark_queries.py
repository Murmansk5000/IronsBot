# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: TC001, TC002
"""Mintmark and gem query matchers."""

from __future__ import annotations

from dataclasses import dataclass

from nonebot.adapters import Event
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.params import Depends
from nonebot.typing import T_State
from seerapi_models import GemCategoryORM, MintmarkClassCategoryORM, MintmarkORM

from ironsbot.integrations.seer_data.mintmark_series_resolvers import (
    resolve_custom_mintmark_series,
)
from ironsbot.integrations.seer_data.sessions import AllSessions
from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.utils.parse_arg import parse_string_arg
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..depends import GetGemCategoryData, GetMintmarkClassData, GetMintmarkData
from ..group import SeerMatcherGroup, seer_feature_rule
from . import mintmark_handlers
from .query_rules import not_rank_query


@dataclass(frozen=True, slots=True)
class MintmarkCommandHandler:
    merge_mode: mintmark_handlers.MintmarkMergeMode

    async def handle(  # noqa: PLR0913
        self,
        matcher: Matcher,
        state: T_State,
        event: Event,
        sessions: AllSessions,
        arg: str = Depends(parse_string_arg),
        mintmarks: tuple[MintmarkORM, ...] = GetMintmarkData(),
        classes: tuple[MintmarkClassCategoryORM, ...] = GetMintmarkClassData(),
    ) -> None:
        if not arg.strip():
            raise FinishedException
        custom_series = resolve_custom_mintmark_series(sessions, arg)
        if custom_series:
            mintmarks = custom_series
            classes = ()

        await mintmark_handlers.handle_mintmark(
            matcher=matcher,
            state=state,
            event=event,
            mintmarks=mintmarks
            + tuple(part.mintmark for item in classes for part in item.mintmark),
            merge_mode=self.merge_mode,
        )


async def _handle_gem(
    matcher: Matcher,
    state: T_State,
    event: Event,
    arg: str = Depends(parse_string_arg),
    categories: tuple[GemCategoryORM, ...] = GetGemCategoryData(),
) -> None:
    if not arg.strip():
        raise FinishedException
    await mintmark_handlers.handle_gem(
        matcher=matcher,
        state=state,
        event=event,
        categories=categories,
    )


def install(group: SeerMatcherGroup) -> None:
    mintmark_matcher = group.on_message(
        policy=CommandPolicy.command("seer_mintmark_query"),
        rule=seer_feature_rule(group.resources.features, "seer_mintmark")
        & startswith_or_endswith("刻印")
        & not_rank_query
        & no_reply(),
        priority=group.matcher_priority("seer_mintmark"),
    )
    mintmark_matcher.append_handler(
        MintmarkCommandHandler(
            (
                "merged"
                if group.resources.config.mintmark.merge_connected
                else "separate"
            ),
        ).handle
    )

    gem_matcher = group.on_message(
        policy=CommandPolicy.command("seer_gem_query"),
        rule=seer_feature_rule(group.resources.features, "seer_mintmark")
        & startswith_or_endswith("宝石")
        & no_reply(),
        priority=group.matcher_priority("seer_mintmark"),
    )
    gem_matcher.append_handler(_handle_gem)
