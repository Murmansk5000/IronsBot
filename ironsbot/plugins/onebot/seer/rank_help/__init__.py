# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import MessageEvent  # noqa: TC002
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.integrations.onebot.context import command_context
from ironsbot.integrations.onebot.feature_policy import event_is_feature_allowed
from ironsbot.integrations.onebot.matchers import (
    CommandPolicy,
    MatcherFactory,
    bind_async,
)
from ironsbot.integrations.onebot.replies import finish_event_reply
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.seer.rank_command_contracts import (
    RANK_HELP_COMMANDS,
    rank_help_command_contracts,
)
from ironsbot.services.seer.rank_help import format_rank_help

if TYPE_CHECKING:
    from ironsbot.core.command_catalog import CommandCatalog
    from ironsbot.core.feature_policy import FeatureService

__plugin_meta__ = PluginMetadata(
    name="榜单",
    description="查看全服、样本、巅峰和刻印相关榜单。",
    usage="发送“榜单”查看当前会话可用的榜单查询方式。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


async def handle_rank_help_entry(
    matcher: Matcher,
    event: MessageEvent,
    *,
    commands: CommandCatalog,
    features: FeatureService,
) -> None:
    command_help = commands.format_for_context(
        command_context(event),
        features,
        plugin_id="rank_help",
    )
    await finish_event_reply(
        matcher,
        event,
        f"📊【可用榜单】\n{format_rank_help(command_help)}",
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
            handle_rank_help_entry,
            commands=commands,
            features=features,
        )
    )


def plugin_contribution(
    *,
    features: FeatureService,
    commands: CommandCatalog,
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
        commands=rank_help_command_contracts(),
        install=partial(install, features=features, commands=commands),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            features=context.resources.features,
            commands=context.resources.commands,
        ),
    )
