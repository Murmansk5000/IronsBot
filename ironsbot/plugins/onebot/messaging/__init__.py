# SPDX-License-Identifier: MIT
"""Configured-message, push and lifecycle contributions for both platforms."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import HelpEntry, PluginContribution, PluginHooks
from ironsbot.services.help_visibility import feature_help_visible
from ironsbot.services.messaging.command_contracts import messaging_command_contracts

if TYPE_CHECKING:
    from ironsbot.config.models.messaging import MessageConfig
    from ironsbot.core.command_catalog import CommandContext
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.messaging.service import MessagingService
    from ironsbot.services.operations.scheduler import Scheduler


def help_visible(
    context: CommandContext,
    *,
    features: FeatureService,
    config: MessageConfig,
) -> bool:
    actions = config.messages
    return feature_help_visible(
        context, features=features, feature="push_topics"
    ) or any(
        action.enabled
        and feature_help_visible(
            context,
            features=features,
            feature=action.feature,
        )
        for action in actions
    )


def plugin_contribution(
    *,
    config: MessageConfig,
    features: FeatureService,
    service: MessagingService,
    scheduler: Scheduler,
) -> PluginContribution:
    """Declare configured message commands and scheduled push lifecycle."""

    commands = messaging_command_contracts(config, service.topics)
    return PluginContribution(
        id="messaging",
        features=frozenset(
            {
                Feature.TEXT,
                Feature.TEXT_PUSH,
                Feature.WEB_ACTIVITY,
                Feature.SEERINFO,
                Feature.PUSH_TOPICS,
            }
        ),
        help=HelpEntry(
            name="文本发送",
            description="按配置回复固定文本/链接，也可定时向群或私聊发送文本",
            group="message",
            order=30,
            visible=partial(help_visible, features=features, config=config),
        ),
        commands=commands,
        hooks=PluginHooks(
            startup=(("messaging", partial(service.start, scheduler)),),
            shutdown=(("push_topics", service.stop_topics),),
        ),
    )
