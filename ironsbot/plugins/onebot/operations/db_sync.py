# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.plugin_install import HelpEntry, PluginContribution
from ironsbot.services.help_visibility import superuser_help_visible
from ironsbot.services.operations.data_sync_commands import data_sync_command_contracts

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService


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
