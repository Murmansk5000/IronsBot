from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import HelpEntry, PluginContribution
from ironsbot.services.messaging.meeting import (
    meeting_command_contracts,
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
