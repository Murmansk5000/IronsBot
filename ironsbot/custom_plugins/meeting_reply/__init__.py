import re

from nonebot import on_regex
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    PrivateMessageEvent,
)

from .config import plugin_config

meeting_matcher = on_regex(r"^(开播|会议)$", priority=5, block=True)


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
async def handle_meeting_reply(event: MessageEvent) -> None:
    if isinstance(event, GroupMessageEvent):
        if event.group_id not in plugin_config.meeting_reply_groups:
            return

    elif isinstance(event, PrivateMessageEvent):
        if event.user_id not in plugin_config.meeting_reply_users:
            return

    reply = build_meeting_reply()
    if not reply:
        return

    await meeting_matcher.finish(Message(reply))
