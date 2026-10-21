# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)
from ironsbot.integrations.onebot.matchers import (
    CommandPolicy,
    MatcherFactory,
)
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.rules import explicit_command, member_targets_command
from ironsbot.services.help_visibility import feature_help_visible
from ironsbot.services.portable_team_resource_commands import (
    build_portable_team_resource_operations,
)
from ironsbot.services.team.resource_commands import team_resource_command_contracts
from ironsbot.services.team.resource_subscriptions import TeamResourceSubscriptionTarget

if TYPE_CHECKING:
    from ironsbot.config.models.seer import TeamResourceConfig
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.operations.scheduler import Scheduler
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.team import SeerTeamQueryService
    from ironsbot.services.team.resource import TeamResourceService

__plugin_meta__ = PluginMetadata(
    name="战队资源订阅",
    description="查询订阅战队的资源，并在资源不足时发送提醒。",
    usage="发送“战队”查看订阅；管理员可发送“订阅战队123456”。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def _is_team_resource_query(
    event: MessageEvent,
    *,
    service: TeamResourceService,
) -> bool:
    context = message_input_context(event)
    target = _subscription_target(event)
    return (
        not context.has_member_mentions
        and target is not None
        and service.matches_target_query(
            event.get_plaintext(),
            actor=context.message.actor,
            target=target,
        )
    )


def _is_team_resource_manage(
    event: MessageEvent,
    *,
    service: TeamResourceService,
) -> bool:
    context = message_input_context(event)
    command = service.parse_manage(event.get_plaintext())
    target = _subscription_target(event)
    return (
        command is not None
        and target is not None
        and service.allows_target(context.message.actor, target)
    )


def install(
    registry: MatcherFactory,
    service: TeamResourceService,
    player_id_resolver: PlayerIdResolver,
    team_query: SeerTeamQueryService,
    query_sessions: PortableQuerySessions,
) -> None:
    if not service.enabled:
        return

    operations = build_portable_team_resource_operations(
        service, player_id_resolver, team_query, query_sessions
    )

    def is_manage(event: MessageEvent) -> bool:
        return _is_team_resource_manage(event, service=service)

    def is_query(event: MessageEvent) -> bool:
        return _is_team_resource_query(event, service=service)

    priority = registry.priority("team_resource_subscription")
    manage_matcher = registry.on_message(
        policy=CommandPolicy.command(
            "team_resource_manage",
            help_ids=(
                "team_resource.subscribe",
                "team_resource.unsubscribe",
                "team_resource.list",
            ),
        ),
        rule=Rule(is_manage) & member_targets_command(),
        priority=priority,
        block=True,
    )
    manage_matcher.append_handler(
        make_portable_query_handler(
            operations["team_resource.subscribe"], query_sessions
        )
    )

    if not service.query_commands:
        return

    query_matcher = registry.on_message(
        policy=CommandPolicy.command(
            "team_resource_query",
            help_ids=("team_resource.query",),
        ),
        rule=Rule(is_query) & explicit_command(),
        priority=priority,
        block=True,
    )
    query_matcher.append_handler(
        make_portable_query_handler(
            operations["team_resource.query"],
            query_sessions,
        )
    )


def plugin_contribution(
    *,
    config: TeamResourceConfig,
    features: FeatureService,
    scheduler: Scheduler,
    service: TeamResourceService,
) -> PluginContribution:
    """Declare team resource commands and scheduled scans."""

    return PluginContribution(
        id="team_resource",
        features=frozenset({Feature.TEAM_RESOURCE_SUBSCRIPTION}),
        help=HelpEntry(
            name="战队资源订阅",
            description="订阅战队，并在资源不足时定时提醒当前会话。",
            group="seer",
            order=50,
            visible=partial(
                feature_help_visible,
                features=features,
                feature="team_resource_subscription",
                enabled=config.enabled,
            ),
        ),
        commands=team_resource_command_contracts(
            enabled=config.enabled, query_commands=service.query_commands
        ),
        hooks=PluginHooks(
            startup=(
                (
                    "team_resource_jobs",
                    partial(service.register_jobs, scheduler),
                ),
            ),
        ),
    )


def _subscription_target(
    event: MessageEvent,
) -> TeamResourceSubscriptionTarget | None:
    context = message_input_context(event)
    if isinstance(event, GroupMessageEvent):
        return TeamResourceSubscriptionTarget(
            context.message.conversation,
            context.member_mentions,
        )
    if isinstance(event, PrivateMessageEvent):
        return TeamResourceSubscriptionTarget(context.message.actor)
    return None


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            config=context.settings.seer.team_resource,
            features=context.resources.features,
            scheduler=context.scheduler,
            service=context.resources.team_resource,
        ),
    )
