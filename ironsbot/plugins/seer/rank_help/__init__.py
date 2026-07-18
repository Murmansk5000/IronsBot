# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.services.seer.rank_usage import (
    RANK_HELP_ENTRY_COMMANDS,
    build_rank_help_message,
)
from ironsbot.shared.features import FeatureService
from ironsbot.shared.features.visibility import event_has_feature
from ironsbot.utils.rule import no_reply


async def handle_rank_help_entry(matcher: Matcher) -> None:
    await matcher.finish(build_rank_help_message())


def install(registry: MatcherRegistry, features: FeatureService) -> None:
    matcher = registry.on_fullmatch(
        RANK_HELP_ENTRY_COMMANDS,
        policy=CommandPolicy.command("seer_rank_help"),
        rule=Rule(lambda event: event_has_feature(features, event, "seer_rank"))
        & no_reply(),
        priority=registry.priority("seer_rank_help", 2),
        block=True,
    )
    matcher.append_handler(handle_rank_help_entry)
