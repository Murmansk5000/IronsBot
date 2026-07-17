# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: TC002
"""Mintmark and gem query matchers."""

from __future__ import annotations

from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.params import Depends
from nonebot.typing import T_State
from seerapi_models import GemCategoryORM, MintmarkClassCategoryORM, MintmarkORM

from ironsbot.utils.parse_arg import parse_string_arg
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..depends import GetGemCategoryData, GetMintmarkClassData, GetMintmarkData
from ..group import matcher_group, seer_feature_priority, seer_feature_rule
from . import mintmark_handlers
from .help_replies import finish_query_help
from .query_rules import not_rank_query

mintmark_matcher = matcher_group.on_message(
    rule=seer_feature_rule("seer_mintmark")
    & startswith_or_endswith("刻印")
    & not_rank_query
    & no_reply(),
    priority=seer_feature_priority("seer_mintmark"),
)


@mintmark_matcher.handle()
async def _handle_mintmark(  # noqa: PLR0913
    matcher: Matcher,
    state: T_State,
    event: Event,
    arg: str = Depends(parse_string_arg),
    mintmarks: tuple[
        MintmarkORM,
        ...,
    ] = GetMintmarkData(),
    classes: tuple[
        MintmarkClassCategoryORM,
        ...,
    ] = GetMintmarkClassData(),
) -> None:
    if not arg.strip():
        await finish_query_help(matcher, event, "mintmark")

    await mintmark_handlers.handle_mintmark(
        matcher=matcher,
        state=state,
        event=event,
        mintmarks=mintmarks,
        classes=classes,
    )


gem_matcher = matcher_group.on_message(
    rule=seer_feature_rule("seer_mintmark")
    & startswith_or_endswith("宝石")
    & no_reply(),
    priority=seer_feature_priority("seer_mintmark"),
)


@gem_matcher.handle()
async def _handle_gem(
    matcher: Matcher,
    state: T_State,
    event: Event,
    arg: str = Depends(parse_string_arg),
    categories: tuple[
        GemCategoryORM,
        ...,
    ] = GetGemCategoryData(),
) -> None:
    if not arg.strip():
        await finish_query_help(matcher, event, "gem")

    await mintmark_handlers.handle_gem(
        matcher=matcher,
        state=state,
        event=event,
        categories=categories,
    )
