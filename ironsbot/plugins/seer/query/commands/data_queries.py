# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: TC001, TC002
"""Seer data query matchers."""

from __future__ import annotations

from nonebot.adapters import Event
from nonebot.matcher import Matcher

from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.utils.rule import no_reply

from ..depends import SeerAPISession
from ..group import SeerMatcherGroup, seer_feature_priority, seer_feature_rule
from . import data_tools


async def _handle_preview(
    session: SeerAPISession,
) -> None:
    await data_tools.handle_preview(session=session)


async def _handle_data_version(
    matcher: Matcher,
    session: SeerAPISession,
) -> None:
    await data_tools.handle_data_version(
        matcher=matcher,
        session=session,
    )


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


def install(group: SeerMatcherGroup) -> None:
    preview_matcher = group.on_fullmatch(
        "下周预告",
        policy=CommandPolicy.command("seer_data_preview"),
        rule=seer_feature_rule(group.features, "seer_data") & no_reply(),
        priority=seer_feature_priority("seer_data"),
    )
    preview_matcher.append_handler(_handle_preview)

    data_version_matcher = group.on_fullmatch(
        "数据版本",
        policy=CommandPolicy.command("seer_data_version"),
        rule=seer_feature_rule(group.features, "seer_data") & no_reply(),
        priority=seer_feature_priority("seer_data"),
    )
    data_version_matcher.append_handler(_handle_data_version)

    season_matcher = group.on_fullmatch(
        ("赛季倒计时", "赛季时间", "赛季结束", "赛季"),
        policy=CommandPolicy.command("seer_season_countdown"),
        rule=seer_feature_rule(group.features, "seer_data") & no_reply(),
        priority=seer_feature_priority("seer_data"),
    )
    season_matcher.append_handler(_handle_season_countdown)
