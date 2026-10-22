# SPDX-License-Identifier: MIT

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import HelpEntry, PluginContribution
from ironsbot.services.about import about_command_contracts
from ironsbot.services.official_identity_info import (
    official_identity_info_command_contracts,
)


def plugin_contribution() -> PluginContribution:
    """Declare the complete runtime contribution owned by this top-level plugin."""

    return PluginContribution(
        id="about",
        features=frozenset({Feature.ABOUT, Feature.QQ_OFFICIAL_IDENTITY_INFO}),
        help=HelpEntry(
            name="关于",
            description="IronsBot 项目信息与当前版本",
            group="core",
            order=20,
        ),
        commands=(
            *about_command_contracts(),
            *official_identity_info_command_contracts(),
        ),
    )
