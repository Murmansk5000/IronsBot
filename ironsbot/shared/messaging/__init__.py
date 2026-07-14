# SPDX-License-Identifier: MIT
from ironsbot.shared.selection_menu import (
    DEFAULT_SELECTION_FOOTER,
    HELP_SELECTION_FOOTER,
    TOGGLE_SELECTION_FOOTER,
    SelectionMenu,
    SelectionMenuItem,
    SelectionMenuSection,
    format_selection_menu,
)

from .admin_notice import (
    ADMIN_NOTICE_FEATURE,
    AdminNoticeTargets,
    admin_notice_targets,
    get_first_onebot_bot,
    send_admin_notice,
)
from .conversations import (
    EventReplyCheck,
    command_reply_check,
    enter_event_reply_conversation,
    event_conversation_session_id,
)
from .query_guard import QueryGuard
from .rate_limits import (
    InMemoryRateLimiter,
    peek_user_rate_limit,
    penalize_user_rate_limit,
    rate_limiter,
)
from .replies import (
    BeforeReplySendHook,
    ReplyMessage,
    apply_reply_before_send,
    configure_reply_delivery_policy,
    event_sender_at_user_ids,
    finish_event_reply,
    finish_matcher_message,
    finish_message_sequence,
    send_event_reply,
    send_matcher_message,
)
from .senders import (
    MessageLimiter,
    OneBotMessageSender,
    get_bot_or_none,
    send_broadcast_message,
    send_target_messages,
)
from .targets import (
    MessageTarget,
    TargetSendSummary,
    broadcast_targets,
    group_targets,
    message_event_target,
    private_targets,
)
from .text import (
    build_message,
    render_text,
)

__all__ = [
    "ADMIN_NOTICE_FEATURE",
    "DEFAULT_SELECTION_FOOTER",
    "HELP_SELECTION_FOOTER",
    "TOGGLE_SELECTION_FOOTER",
    "AdminNoticeTargets",
    "BeforeReplySendHook",
    "EventReplyCheck",
    "InMemoryRateLimiter",
    "MessageLimiter",
    "MessageTarget",
    "OneBotMessageSender",
    "QueryGuard",
    "ReplyMessage",
    "SelectionMenu",
    "SelectionMenuItem",
    "SelectionMenuSection",
    "TargetSendSummary",
    "admin_notice_targets",
    "apply_reply_before_send",
    "broadcast_targets",
    "build_message",
    "command_reply_check",
    "configure_reply_delivery_policy",
    "enter_event_reply_conversation",
    "event_conversation_session_id",
    "event_sender_at_user_ids",
    "finish_event_reply",
    "finish_matcher_message",
    "finish_message_sequence",
    "format_selection_menu",
    "get_bot_or_none",
    "get_first_onebot_bot",
    "group_targets",
    "message_event_target",
    "peek_user_rate_limit",
    "penalize_user_rate_limit",
    "private_targets",
    "rate_limiter",
    "render_text",
    "send_admin_notice",
    "send_broadcast_message",
    "send_event_reply",
    "send_matcher_message",
    "send_target_messages",
]
