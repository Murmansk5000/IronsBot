# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: TC001, TC002
"""Seer data query matchers."""

from __future__ import annotations

from nonebot.adapters import Event
from nonebot.matcher import Matcher

from ironsbot.utils.rule import no_reply

from ..depends import SeerAPISession
from ..group import matcher_group, seer_feature_priority, seer_feature_rule
from . import data_tools

preview_matcher = matcher_group.on_fullmatch(
    "下周预告",
    rule=seer_feature_rule("seer_data") & no_reply(),
    priority=seer_feature_priority("seer_data"),
)


@preview_matcher.handle()
async def _handle_preview(
    session: SeerAPISession,
) -> None:
    await data_tools.handle_preview(session=session)

data_version_matcher = matcher_group.on_fullmatch(
    "数据版本",
    rule=seer_feature_rule("seer_data") & no_reply(),
    priority=seer_feature_priority("seer_data"),
)


@data_version_matcher.handle()
async def _handle_data_version(
    matcher: Matcher,
    session: SeerAPISession,
) -> None:
    await data_tools.handle_data_version(
        matcher=matcher,
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
    await data_tools.handle_season_countdown(
        matcher=matcher,
        event=event,
        session=session,
    )
