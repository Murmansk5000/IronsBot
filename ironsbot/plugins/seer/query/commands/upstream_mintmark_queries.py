# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: TC002
"""Upstream mintmark query matchers."""

from __future__ import annotations

from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.params import Depends
from nonebot.typing import T_State

from ironsbot.utils.parse_arg import parse_string_arg
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..group import matcher_group, seer_feature_priority, seer_feature_rule
from ..upstream_commands import mintmark as upstream_mintmark
from .upstream_query_common import (
    UPSTREAM_QUERY_PLUGIN_NAME,
    dispatch_plugin,
    not_rank_query,
)

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
        upstream_mintmark.MintmarkORM,
        ...,
    ] = upstream_mintmark.GetMintmarkData(),
    classes: tuple[
        upstream_mintmark.MintmarkClassCategoryORM,
        ...,
    ] = upstream_mintmark.GetMintmarkClassData(),
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="mintmark",
        arg=arg,
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
        upstream_mintmark.GemCategoryORM,
        ...,
    ] = upstream_mintmark.GetGemCategoryData(),
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="gem",
        arg=arg,
        categories=categories,
    )
