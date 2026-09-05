# SPDX-License-Identifier: MIT
"""OneBot configured-message commands, push management, and manifest wiring."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
from nonebot.plugin import PluginMetadata

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)
from ironsbot.integrations.onebot.feature_policy import event_is_feature_visible_in_help
from ironsbot.services.messaging.command_contracts import messaging_command_contracts

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from ironsbot.config.models.messaging import MessageConfig
    from ironsbot.config.onebot_references import OneBotReferenceResolver
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.integrations.onebot.matchers import MatcherFactory
    from ironsbot.services.activity.service import ActivityService
    from ironsbot.services.messaging.service import MessagingService
    from ironsbot.services.operations.scheduler import Scheduler

__plugin_meta__ = PluginMetadata(
    name="文本发送",
    description="按配置回复文本或链接，并管理定时推送。",
    usage="发送配置的口令，或发送“推送管理”管理当前会话的推送。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def help_visible(
    event: Event,
    *,
    features: FeatureService,
    config: MessageConfig,
) -> bool:
    if not isinstance(event, (GroupMessageEvent, PrivateMessageEvent)):
        return False
    actions = [*config.commands, *config.keyword_replies, *config.schedules]
    return any(
        action.enabled
        and event_is_feature_visible_in_help(features, event, action.feature)
        for action in actions
    )


def _install(  # noqa: PLR0913 - plugin wiring receives explicit dependencies
    registry: MatcherFactory,
    *,
    messaging: MessagingService,
    references: OneBotReferenceResolver,
    activity_service: ActivityService,
    scheduler: Scheduler,
    command_help_ids: tuple[str, ...],
) -> None:
    from .matchers import install

    refresh_push_time_jobs = partial(
        messaging.refresh_push_time_jobs,
        scheduler=scheduler,
        activity_service=activity_service,
    )
    install(
        registry,
        refresh_push_time_jobs=refresh_push_time_jobs,
        messaging=messaging,
        references=references,
        command_help_ids=command_help_ids,
    )


def plugin_contribution(  # noqa: PLR0913 - plugin wiring receives explicit dependencies
    *,
    config: MessageConfig,
    features: FeatureService,
    references: OneBotReferenceResolver,
    service: MessagingService,
    activity_service: ActivityService,
    scheduler: Scheduler,
) -> PluginContribution:
    """Declare configured message commands and scheduled push lifecycle."""

    commands = messaging_command_contracts(config)
    return PluginContribution(
        id="messaging",
        features=frozenset(
            {
                Feature.TEXT,
                Feature.TEXT_PUSH,
                Feature.WEB_ACTIVITY_LINK,
                Feature.WEB_ACTIVITY_PUSH,
                Feature.SEERINFO,
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
        install=partial(
            _install,
            messaging=service,
            references=references,
            activity_service=activity_service,
            scheduler=scheduler,
            command_help_ids=tuple(
                f"messaging.{action.id}" for action in config.commands if action.enabled
            ),
        ),
        hooks=PluginHooks(
            startup=(("messaging", partial(service.start, scheduler)),),
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            config=context.settings.messaging,
            features=context.resources.features,
            references=context.settings.onebot_references,
            service=context.resources.messaging,
            activity_service=context.resources.activity,
            scheduler=context.scheduler,
        ),
    )
