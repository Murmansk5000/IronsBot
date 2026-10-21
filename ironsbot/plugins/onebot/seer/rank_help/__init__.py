# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.plugin import PluginMetadata

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.services.seer.rank_command_contracts import rank_help_command_contracts

if TYPE_CHECKING:
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver

__plugin_meta__ = PluginMetadata(
    name="榜单",
    description="查看全服、样本、巅峰和刻印相关榜单。",
    usage="发送“榜单”查看当前会话可用的榜单查询方式。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def plugin_contribution(*, player_id_resolver: PlayerIdResolver) -> PluginContribution:
    """Declare rank help metadata and command contracts."""

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
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(player_id_resolver=context.resources.player_id_resolver),
    )
