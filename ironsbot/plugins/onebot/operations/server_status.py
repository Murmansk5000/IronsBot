# SPDX-License-Identifier: MIT
"""Manifest contribution for shared server-status commands."""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.services.operations.server_status_commands import (
    server_status_command_contracts,
)

__plugin_meta__ = PluginMetadata(
    name="开服查询",
    description="查询维护公告与无头客户端游戏连接状态。",
    usage="发送“开服了吗”查询；超级管理员可发送“/开服查询”。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def plugin_contribution() -> PluginContribution:
    """Declare server-status commands and feature ownership."""

    return PluginContribution(
        id="server_status",
        features=frozenset({Feature.SERVER_STATUS_QUERY}),
        help=HelpEntry(
            name="开服查询",
            description="查询赛尔号维护公告，并结合无头客户端连接状态判断是否已开服",
            group="seer",
            order=70,
            notes=(
                "无头客户端已登录游戏服务器时判定为已开服；公告仅作为维护信息摘要。",
            ),
        ),
        commands=server_status_command_contracts(),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(),
    )
