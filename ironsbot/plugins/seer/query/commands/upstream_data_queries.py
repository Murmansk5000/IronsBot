# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: TC001, TC002
"""Upstream data query matchers."""

from __future__ import annotations

from nonebot.adapters import Event
from nonebot.matcher import Matcher

from ironsbot.utils.rule import no_reply

from ..depends import SeerAPISession
from ..group import matcher_group, seer_feature_priority, seer_feature_rule
from .upstream_query_common import UPSTREAM_QUERY_PLUGIN_NAME, dispatch_plugin

preview_matcher = matcher_group.on_fullmatch(
    "下周预告",
    rule=seer_feature_rule("seer_data") & no_reply(),
    priority=seer_feature_priority("seer_data"),
)


@preview_matcher.handle()
async def _handle_preview(
    matcher: Matcher,
    event: Event,
    session: SeerAPISession,
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="preview",
        session=session,
    )

data_version_matcher = matcher_group.on_fullmatch(
    "数据版本",
    rule=seer_feature_rule("seer_data") & no_reply(),
    priority=seer_feature_priority("seer_data"),
)


@data_version_matcher.handle()
async def _handle_data_version(
    matcher: Matcher,
    event: Event,
    session: SeerAPISession,
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="data_version",
        session=session,
    )


season_countdown_matcher = matcher_group.on_fullmatch(
    ("赛季倒计时", "赛季时间", "赛季结束", "赛季"),
    rule=seer_feature_rule("seer_data") & no_reply(),
    priority=seer_feature_priority("seer_data"),
)


@season_countdown_matcher.handle()
async def _handle_season_countdown(
    matcher: Matcher,
    event: Event,
    session: SeerAPISession,
) -> None:
    await dispatch_plugin(
        plugin_name=UPSTREAM_QUERY_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="season_countdown",
        session=session,
    )
