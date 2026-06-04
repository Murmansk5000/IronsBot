from nonebot.plugin import PluginMetadata

from . import runtime as runtime
from .config import Config
from .conversations import (
    command_reply_check,
    enter_event_reply_conversation,
    event_conversation_session_id,
)
from .replies import (
    event_sender_at_user_ids,
    finish_event_reply,
    finish_matcher_message,
    finish_message_sequence,
    send_event_reply,
    send_matcher_message,
)
from .senders import (
    get_bot_or_none,
    send_broadcast_message,
    send_group_messages,
    send_private_messages,
    send_target_messages,
)
from .targets import (
    MessageTarget,
    SendSummary,
    TargetSendSummary,
    broadcast_targets,
    group_targets,
    private_targets,
)
from .text import (
    build_message,
    command_text_matches,
    normalize_command_text,
    render_text,
)

__plugin_meta__ = PluginMetadata(
    name="文本发送",
    description="按配置回复固定文本/链接，也可定时向群或私聊发送文本",
    usage=(
        "【文本发送】\n"
        "按 MSG_PRIVATE_COMMANDS / MSG_GROUP_COMMANDS 中配置的关键词回复固定文本。\n"
        "按 MSG_PRIVATE_SCHEDULES / MSG_GROUP_SCHEDULES 配置定时文本推送。\n"
        "常用场景：签到链接、活动链接、信息聚合页、群公告等。\n"
        "信息聚合页示例：xm / xrym / 雷小伊 / 重聚 -> https://seerinfo.yuyuqaq.cn/"
    ),
    config=Config,
)

__all__ = [
    "MessageTarget",
    "SendSummary",
    "TargetSendSummary",
    "broadcast_targets",
    "build_message",
    "command_reply_check",
    "command_text_matches",
    "enter_event_reply_conversation",
    "event_conversation_session_id",
    "event_sender_at_user_ids",
    "finish_event_reply",
    "finish_matcher_message",
    "finish_message_sequence",
    "get_bot_or_none",
    "group_targets",
    "normalize_command_text",
    "private_targets",
    "render_text",
    "runtime",
    "send_broadcast_message",
    "send_event_reply",
    "send_group_messages",
    "send_matcher_message",
    "send_private_messages",
    "send_target_messages",
]
