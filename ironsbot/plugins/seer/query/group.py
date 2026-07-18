# SPDX-License-Identifier: GPL-3.0-or-later
from dataclasses import dataclass
from typing import Any

from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.services.admin_priority import AdminPriorityService
from ironsbot.services.operations.headless import HeadlessService
from ironsbot.shared.features import FeatureService
from ironsbot.shared.features.visibility import event_has_feature
from ironsbot.shared.matcher_priority import get_matcher_priority

SEER_QUERY_PRIORITY = get_matcher_priority("seer_query", 2)


def seer_feature_rule(features: FeatureService, feature: str) -> Rule:
    async def _is_feature_allowed(event: Event) -> bool:
        return event_has_feature(features, event, feature)

    return Rule(_is_feature_allowed)


def seer_feature_priority(feature: str, fallback: int | None = None) -> int:
    if fallback is None:
        fallback = get_matcher_priority("seer_query", 90)
    return get_matcher_priority(feature, fallback)


@dataclass(frozen=True, slots=True)
class SeerMatcherGroup:
    registry: MatcherRegistry
    headless: HeadlessService
    features: FeatureService
    priority: AdminPriorityService

    def on_message(
        self,
        *,
        policy: CommandPolicy,
        **kwargs: Any,
    ) -> type[Matcher]:
        return self.registry.on_message(
            policy=policy,
            **self._with_defaults(kwargs),
        )

    def on_fullmatch(
        self,
        msg: str | tuple[str, ...],
        *,
        policy: CommandPolicy,
        **kwargs: Any,
    ) -> type[Matcher]:
        return self.registry.on_fullmatch(
            msg,
            policy=policy,
            **self._with_defaults(kwargs),
        )

    @staticmethod
    def _with_defaults(kwargs: dict[str, Any]) -> dict[str, Any]:
        options = dict(kwargs)
        options.setdefault("block", True)
        options.setdefault("priority", SEER_QUERY_PRIORITY)
        return options
