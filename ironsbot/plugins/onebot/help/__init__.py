# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.plugin import PluginMetadata

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    PluginContributionCatalog,
    active_plugin_install_context,
)
from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.integrations.onebot.matchers import CommandPolicy
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.help_commands import help_command_contracts
from ironsbot.services.help_menu import build_portable_help_operation
from ironsbot.services.help_visibility import always_help_visible

__plugin_meta__ = PluginMetadata(
    name="帮助",
    description="按当前会话权限显示可用功能与命令。",
    usage="发送“帮助”。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)

if TYPE_CHECKING:
    from ironsbot.core.command_catalog import CommandCatalog
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.integrations.onebot.matchers import MatcherFactory
    from ironsbot.services.portable_query_sessions import PortableQuerySessions


def install(  # noqa: PLR0913 - shared help dependencies are explicit
    registry: MatcherFactory,
    contribution_catalog: PluginContributionCatalog,
    features: FeatureService,
    commands: CommandCatalog,
    query_sessions: PortableQuerySessions,
    *,
    ignored_plugins: tuple[str, ...],
) -> None:
    operation = build_portable_help_operation(
        contribution_catalog.contributions,
        commands,
        features,
        query_sessions,
        ignored_plugins=ignored_plugins,
    )
    matcher = registry.on_fullmatch(
        "帮助",
        policy=CommandPolicy.command("help", help_ids=("help",)),
        rule=explicit_command(),
        priority=registry.priority("help"),
        block=True,
    )

    matcher.append_handler(
        make_portable_query_handler(
            operation,
            query_sessions,
            ActionDefinition("help", "帮助菜单"),
        )
    )


def plugin_contribution(
    *,
    contribution_catalog: PluginContributionCatalog,
    features: FeatureService,
    commands: CommandCatalog,
    query_sessions: PortableQuerySessions,
    ignored_plugins: tuple[str, ...],
) -> PluginContribution:
    """Declare the help menu against the frozen application contribution view."""

    return PluginContribution(
        id="help",
        features=frozenset({Feature.HELP}),
        help=HelpEntry(
            name="帮助",
            description="按当前群/私聊权限显示可用功能",
            group="core",
            order=10,
            visible=always_help_visible,
        ),
        commands=help_command_contracts(),
        install=partial(
            install,
            contribution_catalog=contribution_catalog,
            features=features,
            commands=commands,
            query_sessions=query_sessions,
            ignored_plugins=ignored_plugins,
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            contribution_catalog=context.resources.contribution_catalog,
            features=context.resources.features,
            commands=context.resources.commands,
            query_sessions=context.resources.query_sessions,
            ignored_plugins=tuple(context.settings.features.help.ignored_plugins),
        ),
    )
