# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from ironsbot.core.features import FeatureService
from ironsbot.runtime.feature_policy import event_is_feature_allowed
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.runtime.replies import finish_event_reply
from ironsbot.runtime.rules import no_reply
from ironsbot.services.seer.rank_usage import (
    RANK_HELP_ENTRY_COMMANDS,
    build_rank_help_message,
)


async def handle_rank_help_entry(
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await finish_event_reply(matcher, event, build_rank_help_message())


def install(registry: MatcherRegistry, features: FeatureService) -> None:
    matcher = registry.on_fullmatch(
        RANK_HELP_ENTRY_COMMANDS,
        policy=CommandPolicy.command("seer_rank_help"),
        rule=Rule(
            lambda event: event_is_feature_allowed(features, event, "seer_rank")
        )
        & no_reply(),
        priority=registry.priority("seer_rank_help"),
        block=True,
    )
    matcher.append_handler(handle_rank_help_entry)
