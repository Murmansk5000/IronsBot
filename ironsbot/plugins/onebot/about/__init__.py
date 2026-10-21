# SPDX-License-Identifier: MIT
from nonebot.plugin import PluginMetadata

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.services.about import about_command_contracts
from ironsbot.services.official_identity_info import (
    official_identity_info_command_contracts,
)

__plugin_meta__ = PluginMetadata(
    name="关于",
    description="显示 IronsBot 项目、版本与鸣谢信息。",
    usage="发送“关于”。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
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


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(),
    )
