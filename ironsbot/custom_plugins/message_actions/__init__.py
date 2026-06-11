from nonebot.plugin import PluginMetadata

from . import reply_limits as reply_limits
from . import runtime as runtime
from .config import Config
from .conversations import (
    command_reply_check,
    enter_event_reply_conversation,
    event_conversation_session_id,
)
from .rate_limits import (
    peek_user_rate_limit,
    penalize_user_rate_limit,
)
from .replies import (
    event_sender_at_user_ids,
    finish_event_reply,
    finish_matcher_message,
    finish_message_sequence,
    send_event_reply,
    send_matcher_message,
)
from .reply_limits import (
    clear_group_reply_line_limit,
    get_group_reply_line_limit,
    limit_message_by_reply_lines,
    limit_text_lines,
    reply_line_limit_for_target,
    set_group_reply_line_limit,
)
from .senders import (
    get_bot_or_none,
    send_broadcast_message,
    send_target_messages,
)
from .targets import (
    MessageTarget,
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
    strip_command_prefix,
)

__plugin_meta__ = PluginMetadata(
    name="文本发送",
    description="按配置回复固定文本/链接，也可定时向群或私聊发送文本",
    usage=(
        "【文本发送】\n"
        "按 message 配置组中的关键词回复固定文本。\n"
        "按 message 配置组中的定时任务推送文本。\n"
        "常用场景：签到链接、活动链接、信息聚合页、群公告等。\n"
        "群主、管理员、超级管理员可发送 /回复行数 20 设置本群回复消息行数，防止刷屏。\n"
        "信息聚合页示例：xm / xrym / 雷小伊 / 重聚 -> https://seerinfo.yuyuqaq.cn/"
    ),
    config=Config,
)

__all__ = [
    "MessageTarget",
    "TargetSendSummary",
    "broadcast_targets",
    "build_message",
    "clear_group_reply_line_limit",
    "command_reply_check",
    "command_text_matches",
    "enter_event_reply_conversation",
    "event_conversation_session_id",
    "event_sender_at_user_ids",
    "finish_event_reply",
    "finish_matcher_message",
    "finish_message_sequence",
    "get_bot_or_none",
    "get_group_reply_line_limit",
    "group_targets",
    "limit_message_by_reply_lines",
    "limit_text_lines",
    "normalize_command_text",
    "peek_user_rate_limit",
    "penalize_user_rate_limit",
    "private_targets",
    "render_text",
    "reply_limits",
    "reply_line_limit_for_target",
    "runtime",
    "send_broadcast_message",
    "send_event_reply",
    "send_matcher_message",
    "send_target_messages",
    "set_group_reply_line_limit",
    "strip_command_prefix",
]
