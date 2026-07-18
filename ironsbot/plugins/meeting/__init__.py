from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from ironsbot.config.models.message import MeetingConfig
from ironsbot.core.commands import command_text_matches
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.shared.features import FeatureService
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import finish_event_reply
from ironsbot.utils.rule import no_reply

from .service import build_meeting_reply, is_meeting_command_event


def install(
    registry: MatcherRegistry,
    config: MeetingConfig,
    features: FeatureService,
) -> None:
    async def is_meeting_command(event: MessageEvent) -> bool:
        return is_meeting_command_event(
            event,
            config,
            is_group_allowed=features.is_group_feature_allowed,
            is_private_allowed=features.is_private_feature_allowed,
            command_matches=command_text_matches,
        )

    async def handle_meeting_reply(
        matcher: Matcher,
        event: MessageEvent,
    ) -> None:
        reply = build_meeting_reply(config)
        if not reply:
            logger.warning(
                "meeting command matched but message.meeting.number is empty"
            )
            await finish_event_reply(
                matcher,
                event,
                "会议号还没有配置，请在 message.meeting.number 中填写腾讯会议号。",
                mention_sender=True,
            )
            return

        await finish_event_reply(matcher, event, reply)

    matcher = registry.on_message(
        policy=CommandPolicy.command("meeting"),
        rule=Rule(is_meeting_command) & no_reply(),
        priority=get_matcher_priority("meeting", 5),
        block=True,
    )
    matcher.append_handler(handle_meeting_reply)
