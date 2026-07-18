from nonebot.adapters.onebot.v11 import (
    MessageEvent,
)
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from ironsbot.core.commands import command_text_matches
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.shared.features import (
    is_group_feature_allowed,
    is_private_feature_allowed,
)
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import (
    finish_event_reply,
)
from ironsbot.utils.rule import no_reply

from .config import get_meeting_config
from .service import build_meeting_reply, is_meeting_command_event


async def _is_meeting_command(event: MessageEvent) -> bool:
    return is_meeting_command_event(
        event,
        get_meeting_config(),
        is_group_allowed=is_group_feature_allowed,
        is_private_allowed=is_private_feature_allowed,
        command_matches=command_text_matches,
    )


async def handle_meeting_reply(matcher: Matcher, event: MessageEvent) -> None:
    config = get_meeting_config()
    reply = build_meeting_reply(config)
    if not reply:
        logger.warning("meeting command matched but message.meeting.number is empty")
        await finish_event_reply(
            matcher,
            event,
            "会议号还没有配置，请在 message.meeting.number 中填写腾讯会议号。",
            mention_sender=True,
        )
        return

    await finish_event_reply(matcher, event, reply)


def install(registry: MatcherRegistry) -> None:
    matcher = registry.on_message(
        policy=CommandPolicy.command("meeting"),
        rule=Rule(_is_meeting_command) & no_reply(),
        priority=get_matcher_priority("meeting", 5),
        block=True,
    )
    matcher.append_handler(handle_meeting_reply)
