from nonebot import on_message
from nonebot.adapters.onebot.v11 import (
    MessageEvent,
)
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.shared.messaging import (
    finish_event_reply,
)
from ironsbot.shared.features import (
    is_group_feature_allowed,
    is_private_feature_allowed,
)
from ironsbot.shared.messaging.text import command_text_matches
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.rule import no_reply

from .config import get_meeting_config
from .service import build_meeting_reply, is_meeting_command_event

__plugin_meta__ = PluginMetadata(
    name="\u4f1a\u8bae\u56de\u590d",
    description="\u6309\u914d\u7f6e\u56de\u590d\u817e\u8baf\u4f1a\u8bae\u4fe1\u606f",
    usage=(
        "\u3010\u4f1a\u8bae\u56de\u590d\u3011\n"
        "群聊或私聊发送 message.meeting.commands 中配置的口令。\n"
        "Access is controlled by FEATURE_GROUP_POLICY / FEATURE_USER_POLICY "
        "feature: meeting."
    ),
)

MEETING_PLUGIN_NAME = "meeting"


async def _is_meeting_command(event: MessageEvent) -> bool:
    return is_meeting_command_event(
        event,
        get_meeting_config(),
        is_group_allowed=is_group_feature_allowed,
        is_private_allowed=is_private_feature_allowed,
        command_matches=command_text_matches,
    )


meeting_matcher = on_message(
    rule=Rule(_is_meeting_command) & no_reply(),
    priority=5,
    block=True,
)


class MeetingReplyPlugin:
    name = MEETING_PLUGIN_NAME
    feature = "meeting"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        matcher = context.matcher or meeting_matcher
        config = get_meeting_config()
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


register_plugin(MeetingReplyPlugin())


@meeting_matcher.handle()
async def handle_meeting_reply(matcher: Matcher, event: MessageEvent) -> None:
    await dispatch_plugin(
        plugin_name=MEETING_PLUGIN_NAME,
        event=event,
        matcher=matcher,
    )
