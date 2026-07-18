# SPDX-License-Identifier: GPL-3.0-or-later
"""Seer data query matchers."""

from __future__ import annotations

from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.utils.rule import no_reply

from ..group import SeerMatcherGroup, seer_feature_rule
from . import data_tools


def install(group: SeerMatcherGroup) -> None:
    preview_matcher = group.on_fullmatch(
        "下周预告",
        policy=CommandPolicy.command("seer_data_preview"),
        rule=seer_feature_rule(group.resources.features, "seer_data") & no_reply(),
        priority=group.matcher_priority("seer_data"),
    )
    preview_matcher.append_handler(data_tools.handle_preview)

    data_version_matcher = group.on_fullmatch(
        "数据版本",
        policy=CommandPolicy.command("seer_data_version"),
        rule=seer_feature_rule(group.resources.features, "seer_data") & no_reply(),
        priority=group.matcher_priority("seer_data"),
    )
    data_version_matcher.append_handler(data_tools.handle_data_version)

    season_matcher = group.on_fullmatch(
        ("赛季倒计时", "赛季时间", "赛季结束", "赛季"),
        policy=CommandPolicy.command("seer_season_countdown"),
        rule=seer_feature_rule(group.resources.features, "seer_data") & no_reply(),
        priority=group.matcher_priority("seer_data"),
    )
    season_matcher.append_handler(
        data_tools.SeasonCountdownHandler(
            group.resources.config.season
        ).handle
    )
