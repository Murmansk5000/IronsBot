# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.integrations.onebot.feature_policy import event_is_feature_allowed
from ironsbot.integrations.onebot.matchers import (
    CommandPolicy,
    MatcherFactory,
    bind_async,
)
from ironsbot.integrations.onebot.replies import run_portable_operation
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.portable_seer_commands import (
    build_portable_rank_help_operation,
)
from ironsbot.services.seer.rank_command_contracts import (
    RANK_HELP_COMMANDS,
    rank_help_command_contracts,
)

if TYPE_CHECKING:
    from ironsbot.core.command_catalog import CommandCatalog
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver

__plugin_meta__ = PluginMetadata(
    name="榜单",
    description="查看全服、样本、巅峰和刻印相关榜单。",
    usage="发送“榜单”查看当前会话可用的榜单查询方式。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def install(
    registry: MatcherFactory,
    features: FeatureService,
    commands: CommandCatalog,
) -> None:
    matcher = registry.on_fullmatch(
        RANK_HELP_COMMANDS,
        policy=CommandPolicy.command("seer_rank_help", help_ids=("rank.help",)),
        rule=Rule(lambda event: event_is_feature_allowed(features, event, "seer_rank"))
        & explicit_command(),
        priority=registry.priority("seer_rank_help"),
        block=True,
    )
    matcher.append_handler(
        bind_async(
            run_portable_operation,
            operation=build_portable_rank_help_operation(commands, features),
        )
    )


def plugin_contribution(
    *,
    features: FeatureService,
    commands: CommandCatalog,
    player_id_resolver: PlayerIdResolver,
) -> PluginContribution:
    """Declare rank help metadata, command contracts, and matcher installer."""

    return PluginContribution(
        id="rank_help",
        features=frozenset({Feature.SEER_RANK}),
        help=HelpEntry(
            name="榜单",
            description="查看全服榜、机器人样本榜、巅峰样本榜和刻印数值榜",
            group="seer",
            order=20,
        ),
        commands=rank_help_command_contracts(player_id_resolver),
        install=partial(install, features=features, commands=commands),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            features=context.resources.features,
            commands=context.resources.commands,
            player_id_resolver=context.resources.player_id_resolver,
        ),
    )
