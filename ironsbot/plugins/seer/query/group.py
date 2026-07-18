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


def seer_feature_rule(features: FeatureService, feature: str) -> Rule:
    async def _is_feature_allowed(event: Event) -> bool:
        return event_has_feature(features, event, feature)

    return Rule(_is_feature_allowed)


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

    def matcher_priority(self, feature: str, fallback: int | None = None) -> int:
        return self.registry.priority(
            feature,
            fallback
            if fallback is not None
            else self.registry.priority("seer_query", 90),
        )

    def _with_defaults(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        options = dict(kwargs)
        options.setdefault("block", True)
        options.setdefault("priority", self.registry.priority("seer_query", 2))
        return options
