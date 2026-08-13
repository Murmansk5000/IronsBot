from functools import partial

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.log import logger
from nonebot.matcher import Matcher
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
from ironsbot.integrations.onebot.matchers import CommandPolicy, MatcherFactory
from ironsbot.integrations.onebot.replies import finish_event_reply
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.messaging.meeting import (
    build_meeting_reply,
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


def install(
    registry: MatcherFactory,
    commands: tuple[str, ...],
    number: str,
    template: str,
    features: FeatureService,
) -> None:
    async def is_meeting_command(event: MessageEvent) -> bool:
        return event_is_feature_allowed(
            features, event, "meeting"
        ) and command_text_matches(event.get_plaintext(), commands)

    async def handle_meeting_reply(
        matcher: Matcher,
        event: MessageEvent,
    ) -> None:
        reply = build_meeting_reply(number, template)
        if not reply:
            logger.warning(
                "meeting command matched but messaging.meeting.number is empty"
            )
            await finish_event_reply(
                matcher,
                event,
                "会议号还没有配置，请在 messaging.meeting.number 中填写腾讯会议号。",
            )
            return

        await finish_event_reply(matcher, event, reply)

    matcher = registry.on_message(
        policy=CommandPolicy.command("meeting", help_ids=("meeting",)),
        rule=Rule(is_meeting_command) & explicit_command(),
        priority=registry.priority("meeting"),
        block=True,
    )
    matcher.append_handler(handle_meeting_reply)


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
