# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Any

from nonebot import MatcherGroup
from nonebot.rule import Rule

from ironsbot.custom_plugins.superuser_policy import is_custom_feature_event_allowed


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
    priority=2,
    rule=Rule(is_custom_feature_event_allowed),
)
