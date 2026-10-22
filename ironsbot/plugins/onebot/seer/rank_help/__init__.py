# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import HelpEntry, PluginContribution
from ironsbot.services.seer.rank_command_contracts import rank_help_command_contracts

if TYPE_CHECKING:
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver


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
