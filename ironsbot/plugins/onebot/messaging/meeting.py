from functools import partial

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.core.commands import command_text_matches
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.integrations.onebot.feature_policy import event_is_feature_allowed
from ironsbot.integrations.onebot.matchers import (
    CommandPolicy,
    MatcherFactory,
    bind_async,
)
from ironsbot.integrations.onebot.replies import run_portable_operation
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.messaging.meeting import meeting_command_contracts
from ironsbot.services.portable_operational_commands import (
    build_portable_meeting_operations,
)

__plugin_meta__ = PluginMetadata(
    name="会议回复",
    description="按配置回复腾讯会议信息。",
    usage="发送已配置的会议口令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def install(
    registry: MatcherFactory,
    commands: tuple[str, ...],
    number: str,
    template: str,
    features: FeatureService,
) -> None:
    operation = build_portable_meeting_operations(number, template)["meeting"]

    async def is_meeting_command(event: MessageEvent) -> bool:
        return event_is_feature_allowed(
            features, event, "meeting"
        ) and command_text_matches(event.get_plaintext(), commands)

    matcher = registry.on_message(
        policy=CommandPolicy.command("meeting", help_ids=("meeting",)),
        rule=Rule(is_meeting_command) & explicit_command(),
        priority=registry.priority("meeting"),
        block=True,
    )
    matcher.append_handler(
        bind_async(run_portable_operation, operation=operation)
    )


def plugin_contribution(
    *,
    commands: tuple[str, ...],
    number: str,
    template: str,
    features: FeatureService,
) -> PluginContribution:
    """Declare the meeting command and its configured matcher installer."""

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
        install=partial(
            install,
            commands=commands,
            number=number,
            template=template,
            features=features,
        ),
    )


if (context := active_plugin_install_context()) is not None:
    meeting = context.settings.messaging.meeting
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            commands=tuple(meeting.commands),
            number=meeting.number,
            template=meeting.template,
            features=context.resources.features,
        ),
    )
