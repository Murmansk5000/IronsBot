# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Any

from nonebot import MatcherGroup
from nonebot.adapters import Event
from nonebot.rule import Rule

from ironsbot.shared.features import is_event_feature_allowed
from ironsbot.shared.matcher_priority import get_matcher_priority


async def is_seer_event_allowed(event: Event) -> bool:
    return is_event_feature_allowed(event, "seer")


def seer_feature_rule(feature: str) -> Rule:
    async def _is_feature_allowed(event: Event) -> bool:
        return is_event_feature_allowed(event, feature)

    return Rule(_is_feature_allowed)


def seer_feature_priority(feature: str, fallback: int | None = None) -> int:
    if fallback is None:
        fallback = get_matcher_priority("seer_query", 90)
    return get_matcher_priority(feature, fallback)


class CustomFeatureMatcherGroup(MatcherGroup):
    def _get_final_kwargs(
        self,
        update: dict[str, Any],
        *,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        final_kwargs = super()._get_final_kwargs(update, exclude=exclude)
        base_rule = self.base_kwargs.get("rule")
        update_rule = update.get("rule")
        if isinstance(base_rule, Rule) and isinstance(update_rule, Rule):
            final_kwargs["rule"] = base_rule & update_rule
        return final_kwargs


matcher_group = CustomFeatureMatcherGroup(
    block=True,
    priority=get_matcher_priority("seer_query", 2),
)
