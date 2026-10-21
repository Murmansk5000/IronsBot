from nonebot.plugin import PluginMetadata

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.services.messaging.meeting import (
    meeting_command_contracts,
)

__plugin_meta__ = PluginMetadata(
    name="会议回复",
    description="按配置回复腾讯会议信息。",
    usage="发送已配置的会议口令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def plugin_contribution(*, commands: tuple[str, ...]) -> PluginContribution:
    """Declare the configured meeting command visibility."""

    return PluginContribution(
        id="meeting",
        features=frozenset({Feature.MEETING}),
        help=HelpEntry(
            name="会议回复",
            description="按配置回复腾讯会议信息",
            group="message",
            order=40,
        ),
        commands=meeting_command_contracts(commands),
    )


if (context := active_plugin_install_context()) is not None:
    meeting = context.settings.messaging.meeting
    context.contribute(
        __plugin_meta__,
        plugin_contribution(commands=tuple(meeting.commands)),
    )
