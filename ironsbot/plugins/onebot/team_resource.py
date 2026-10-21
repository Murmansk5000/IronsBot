# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.plugin import PluginMetadata

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)
from ironsbot.services.help_visibility import feature_help_visible
from ironsbot.services.team.resource_commands import team_resource_command_contracts

if TYPE_CHECKING:
    from ironsbot.config.models.seer import TeamResourceConfig
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.operations.scheduler import Scheduler
    from ironsbot.services.team.resource import TeamResourceService

__plugin_meta__ = PluginMetadata(
    name="战队资源订阅",
    description="查询订阅战队的资源，并在资源不足时发送提醒。",
    usage="发送“战队”查看订阅；管理员可发送“订阅战队123456”。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
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
