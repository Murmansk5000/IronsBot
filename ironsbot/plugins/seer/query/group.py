# SPDX-License-Identifier: GPL-3.0-or-later
from dataclasses import dataclass
from typing import Any

from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.services.operations.headless import HeadlessService
from ironsbot.shared.features import is_event_feature_allowed
from ironsbot.shared.matcher_priority import get_matcher_priority

SEER_QUERY_PRIORITY = get_matcher_priority("seer_query", 2)


def seer_feature_rule(feature: str) -> Rule:
    async def _is_feature_allowed(event: Event) -> bool:
        return is_event_feature_allowed(event, feature)

    return Rule(_is_feature_allowed)


def seer_feature_priority(feature: str, fallback: int | None = None) -> int:
    if fallback is None:
        fallback = get_matcher_priority("seer_query", 90)
    return get_matcher_priority(feature, fallback)


@dataclass(frozen=True, slots=True)
class SeerMatcherGroup:
    registry: MatcherRegistry
    headless: HeadlessService

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


__all__ = [
    "SEER_QUERY_PRIORITY",
    "SeerMatcherGroup",
    "seer_feature_priority",
    "seer_feature_rule",
]
