from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from ironsbot.core.commands import command_text_matches
from ironsbot.core.features import FeatureService
from ironsbot.runtime.feature_policy import event_is_feature_allowed
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.runtime.message_input import message_input_context
from ironsbot.runtime.replies import (
    event_sender_at_user_ids,
    finish_event_reply,
    finish_matcher_message,
)
from ironsbot.runtime.rules import member_targets_command
from ironsbot.services.messaging.meeting import build_meeting_reply


def install(
    registry: MatcherRegistry,
    commands: tuple[str, ...],
    number: str,
    template: str,
    features: FeatureService,
) -> None:
    async def is_meeting_command(event: MessageEvent) -> bool:
        context = message_input_context(event)
        return (
            event_is_feature_allowed(features, event, "meeting")
            and command_text_matches(context.text, commands)
            and (not context.has_member_mentions or bool(context.member_user_ids))
        )

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

        targets = message_input_context(event).member_user_ids
        await finish_matcher_message(
            matcher,
            reply,
            at_user_ids=targets or event_sender_at_user_ids(event),
            event=event,
        )

    matcher = registry.on_message(
        policy=CommandPolicy.command("meeting", help_ids=("meeting",)),
        rule=Rule(is_meeting_command) & member_targets_command(),
        priority=registry.priority("meeting"),
        block=True,
    )
    matcher.append_handler(handle_meeting_reply)
