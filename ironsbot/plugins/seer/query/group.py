# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.rule import Rule

from ironsbot.runtime.feature_policy import event_is_feature_allowed

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nonebot.matcher import Matcher

    from ironsbot.core.features import FeatureService
    from ironsbot.runtime.commands import CommandCatalog
    from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
    from ironsbot.services.seer.resources import SeerQueryResources


def seer_feature_rule(features: FeatureService, feature: str) -> Rule:
    async def _is_feature_allowed(event: Event) -> bool:
        return event_is_feature_allowed(features, event, feature)

    return Rule(_is_feature_allowed)


@dataclass(frozen=True, slots=True)
class SeerMatcherGroup:
    registry: MatcherRegistry
    resources: SeerQueryResources
    features: FeatureService
    commands: CommandCatalog
    release_priority: Callable[[dict[str, Any]], Awaitable[None]]

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

    def matcher_priority(self, feature: str) -> int:
        return self.registry.priority(feature)

    def _with_defaults(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        options = dict(kwargs)
        options.setdefault("block", True)
        options.setdefault("priority", self.registry.priority("seer_query"))
        return options
