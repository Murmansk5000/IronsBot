import re

from nonebot import on_message
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from ironsbot.custom_plugins.message_actions import (
    command_text_matches,
    finish_event_reply,
)
from ironsbot.custom_plugins.superuser_policy import (
    is_group_allowed_for_user,
    is_private_user_allowed,
)
from ironsbot.utils.rule import no_reply

from .config import plugin_config

MEETING_COMMANDS = ("开播", "会议")


async def _is_meeting_command(event: MessageEvent) -> bool:
    if isinstance(event, GroupMessageEvent):
        if not is_group_allowed_for_user(
            event.user_id,
            event.group_id,
            plugin_config.meeting_reply_groups,
        ):
            return False
    elif isinstance(event, PrivateMessageEvent):
        if not is_private_user_allowed(
            event.user_id,
            plugin_config.meeting_reply_users,
        ):
            return False
    else:
        return False

    return command_text_matches(event.get_plaintext(), MEETING_COMMANDS)


meeting_matcher = on_message(
    rule=Rule(_is_meeting_command) & no_reply(),
    priority=5,
    block=True,
)


def build_meeting_reply() -> str:
    raw_number = plugin_config.meeting_reply_number.strip()
    digits = re.sub(r"\D", "", raw_number)
    if not digits:
        return ""

    if len(digits) == 10:
        meeting_number = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    else:
        meeting_number = raw_number

    meeting_url = f"https://meeting.tencent.com/p/{digits}"
    return plugin_config.meeting_reply_template.format(
        meeting_number=meeting_number,
        meeting_digits=digits,
        meeting_url=meeting_url,
    )


@meeting_matcher.handle()
async def handle_meeting_reply(matcher: Matcher, event: MessageEvent) -> None:
    reply = build_meeting_reply()
    if not reply:
        return

    await finish_event_reply(matcher, event, reply)
