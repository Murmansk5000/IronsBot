import re

from nonebot import on_message
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.custom_plugins.feature_policy import (
    is_group_feature_allowed,
    is_private_feature_allowed,
)
from ironsbot.custom_plugins.message_actions import (
    command_text_matches,
    finish_event_reply,
)
from ironsbot.utils.rule import no_reply

from .config import plugin_config

TENCENT_MEETING_NUMBER_DIGITS = 10

__plugin_meta__ = PluginMetadata(
    name="\u4f1a\u8bae\u56de\u590d",
    description="\u6309\u914d\u7f6e\u56de\u590d\u817e\u8baf\u4f1a\u8bae\u4fe1\u606f",
    usage=(
        "\u3010\u4f1a\u8bae\u56de\u590d\u3011\n"
        "群聊或私聊发送 MEETING_CONFIG.commands 中配置的口令。\n"
        "Access is controlled by FEATURE_GROUP_POLICY / FEATURE_USER_POLICY "
        "feature: meeting."
    ),
)


async def _is_meeting_command(event: MessageEvent) -> bool:
    if isinstance(event, GroupMessageEvent):
        if not is_group_feature_allowed(
            event.user_id,
            event.group_id,
            "meeting",
        ):
            return False
    elif isinstance(event, PrivateMessageEvent):
        if not is_private_feature_allowed(
            event.user_id,
            "meeting",
        ):
            return False
    else:
        return False

    return command_text_matches(
        event.get_plaintext(),
        plugin_config.meeting_config.commands,
    )


meeting_matcher = on_message(
    rule=Rule(_is_meeting_command) & no_reply(),
    priority=5,
    block=True,
)


def build_meeting_reply() -> str:
    raw_number = plugin_config.meeting_config.number.strip()
    digits = re.sub(r"\D", "", raw_number)
    if not digits:
        return ""

    if len(digits) == TENCENT_MEETING_NUMBER_DIGITS:
        meeting_number = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    else:
        meeting_number = raw_number

    meeting_url = f"https://meeting.tencent.com/p/{digits}"
    template = plugin_config.meeting_config.template.replace("\\n", "\n")
    return template.format(
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
