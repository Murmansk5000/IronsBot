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
    name="链接",
    description="按配置回复固定链接/文本，也可定时向群或私聊发送消息",
    usage=(
        "【链接】\n"
        "按 MSG_PRIVATE_COMMANDS / MSG_GROUP_COMMANDS 中配置的关键词回复固定文本。\n"
        "常用场景：链接、活动、签到、信息聚合页等。\n"
        "定时推送由 MSG_PRIVATE_SCHEDULES / MSG_GROUP_SCHEDULES 配置。"
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
