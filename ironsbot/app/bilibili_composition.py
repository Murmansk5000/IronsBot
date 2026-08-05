# SPDX-License-Identifier: MIT
"""OneBot Bilibili monitor assembly owned by application composition."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.integrations.onebot.bilibili_auth import send_bili_login_notice
from ironsbot.integrations.onebot.bilibili_push import OneBotBilibiliPushSender
from ironsbot.integrations.onebot.bilibili_rendering import (
    build_dynamic_content_message,
    build_dynamic_link_message,
)
from ironsbot.runtime.replies import append_text_hint
from ironsbot.services.bilibili.runtime import BilibiliMonitorService

if TYPE_CHECKING:
    from ironsbot.core.bilibili import BiliConfig
    from ironsbot.integrations.onebot.delivery import MessageLimiter, OneBotDelivery
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.bilibili.login import BilibiliLoginService
    from ironsbot.services.bilibili.service import BilibiliService
    from ironsbot.services.messaging.admin_notice import AdminNoticeService
    from ironsbot.services.messaging.subscriptions import PushSubscriptionRepository


def build_onebot_bilibili_monitor(  # noqa: PLR0913 - composition root
    *,
    service: BilibiliService,
    login: BilibiliLoginService,
    delivery: OneBotDelivery,
    subscriptions: PushSubscriptionRepository,
    admin_notices: AdminNoticeService,
    message_limiter: MessageLimiter,
    ai_service: AiService,
    config: BiliConfig,
) -> BilibiliMonitorService:
    """Assemble the OneBot push sender without exposing it to the plugin."""
    notice_sender = partial(send_bili_login_notice, admin_notices)
    auth_invalid = partial(
        login.notify_required,
        send_notice=notice_sender,
        is_online=lambda: delivery.default_bot() is not None,
    )
    push_delivery = OneBotBilibiliPushSender(
        delivery,
        subscriptions,
        build_dynamic_link_message,
        build_dynamic_content_message,
        append_text_hint,
        message_limiter,
        getattr(ai_service, "summarize_bilibili_dynamic", None),
        config.push.content_max_chars,
        config.push.summary_max_chars,
        config.push.summary_use_ai,
        service.targets.can_conversation_query_history,
        admin_notices,
    )
    return BilibiliMonitorService(service, auth_invalid, push_delivery.send)
