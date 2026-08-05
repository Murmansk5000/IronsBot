# SPDX-License-Identifier: MIT
"""Highest-priority silent block for configured conversation sources."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.exception import FinishedException
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.core.features import Feature
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry, bind
from ironsbot.runtime.message_input import message_input_context
from ironsbot.runtime.plugins import (
    PluginContribution,
    active_plugin_install_context,
)

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent

    from ironsbot.core.feature_policy import FeatureService


BLACKLIST_PRIORITY = -1_000

__plugin_meta__ = PluginMetadata(
    name="会话黑名单",
    description="静默拦截配置的用户或群会话。",
    usage="由 feature 配置管理，无直接用户命令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def event_is_blacklisted(
    features: FeatureService,
    event: MessageEvent,
) -> bool:
    message = message_input_context(event).message
    return features.is_message_blocked(message.actor, message.conversation)


def install(
    registry: MatcherRegistry,
    features: FeatureService,
) -> None:
    async def discard(_matcher: Matcher) -> None:
        raise FinishedException

    matcher = registry.on_message(
        policy=CommandPolicy.exempt("conversation blacklist"),
        rule=Rule(bind(event_is_blacklisted, features)),
        priority=BLACKLIST_PRIORITY,
        block=True,
    )
    matcher.append_handler(discard)


def plugin_contribution(*, features: FeatureService) -> PluginContribution:
    """Declare the silent blacklist matcher owned by this plugin."""

    return PluginContribution(
        id="conversation_blacklist",
        features=frozenset({Feature.BLACKLIST}),
        install=partial(install, features=features),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(features=context.resources.features),
    )
