# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.plugin import PluginMetadata

from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.services.help_visibility import superuser_help_visible
from ironsbot.services.operations.data_sync_commands import data_sync_command_contracts

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService

__plugin_meta__ = PluginMetadata(
    name="数据更新",
    description="构建远程数据并同步赛尔数据库与别名数据库。",
    usage="超级管理员发送“/更新数据”或“/强制更新数据”；也支持“/同步数据”和“/强制同步数据”。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def plugin_contribution(*, features: FeatureService) -> PluginContribution:
    """Declare the OneBot administrator commands for application-owned sync."""

    return PluginContribution(
        id="db_sync",
        help=HelpEntry(
            name="数据更新",
            description="构建并同步赛尔数据库与别名数据库",
            group="admin",
            order=20,
            visible=partial(superuser_help_visible, features=features),
        ),
        commands=data_sync_command_contracts(),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(features=context.resources.features),
    )
