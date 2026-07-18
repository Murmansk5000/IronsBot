# SPDX-License-Identifier: GPL-3.0-or-later
"""Element type and battle effect query matchers."""

from __future__ import annotations

from functools import partial

from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..group import SeerMatcherGroup, seer_feature_rule
from . import battle_effect_handlers, type_handlers


def install(group: SeerMatcherGroup) -> None:
    type_matcher = group.on_message(
        policy=CommandPolicy.command("seer_type_query"),
        rule=seer_feature_rule(group.resources.features, "seer_type")
        & startswith_or_endswith("属性")
        & no_reply(),
        priority=group.matcher_priority("seer_type"),
    )
    type_matcher.append_handler(
        partial(type_handlers.handle_type, group.resources.render_cache)
    )

    effect_matcher = group.on_message(
        policy=CommandPolicy.command("seer_battle_effect_query"),
        rule=seer_feature_rule(group.resources.features, "seer_type")
        & startswith_or_endswith(
            ("异常", "查询异常状态"),
            suffixes="异常",
        )
        & no_reply(),
        priority=group.matcher_priority("seer_type"),
    )
    effect_matcher.append_handler(battle_effect_handlers.handle_battle_effect)
