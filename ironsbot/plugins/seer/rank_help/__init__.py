# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from nonebot.adapters.onebot.v11 import MessageEvent  # noqa: TC002
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.rule import Rule

from ironsbot.core.features import FeatureService  # noqa: TC001
from ironsbot.runtime.commands import CommandCatalog  # noqa: TC001
from ironsbot.runtime.feature_policy import event_is_feature_allowed
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry, bind_async
from ironsbot.runtime.replies import finish_event_reply
from ironsbot.runtime.rules import no_reply


async def handle_rank_help_entry(
    matcher: Matcher,
    event: MessageEvent,
    *,
    commands: CommandCatalog,
    features: FeatureService,
) -> None:
    await finish_event_reply(
        matcher,
        event,
        "📊【可用榜单】\n"
        f"{commands.format_for(event, features, plugin_id='rank_help')}",
    )


def install(
    registry: MatcherRegistry,
    features: FeatureService,
    commands: CommandCatalog,
) -> None:
    matcher = registry.on_fullmatch(
        ("榜单", "排行榜"),
        policy=CommandPolicy.command("seer_rank_help"),
        rule=Rule(
            lambda event: event_is_feature_allowed(features, event, "seer_rank")
        )
        & no_reply(),
        priority=registry.priority("seer_rank_help"),
        block=True,
    )
    matcher.append_handler(
        bind_async(
            handle_rank_help_entry,
            commands=commands,
            features=features,
        )
    )
