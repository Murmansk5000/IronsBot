# SPDX-License-Identifier: MIT
"""Construct the Bilibili polling and delivery runtime."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.plugins.bilibili.auth import send_bili_login_notice
from ironsbot.plugins.bilibili.delivery import (
    build_dynamic_images_message,
    build_dynamic_link_message,
    build_dynamic_text_message,
)
from ironsbot.runtime.replies import append_text_hint, prepend_text_hint
from ironsbot.services.bilibili.delivery import BilibiliPushDeliveryService
from ironsbot.services.bilibili.runtime import BilibiliMonitorService

if TYPE_CHECKING:
    from ironsbot.app.resources import ApplicationResources
    from ironsbot.config.models.settings import Settings


def build_bilibili_monitor(
    settings: Settings,
    resources: ApplicationResources,
) -> BilibiliMonitorService:
    service = resources.bilibili
    auth_invalid = partial(
        resources.bilibili_login.notify_required,
        send_notice=partial(send_bili_login_notice, resources.admin_notices),
        is_online=lambda: resources.delivery.default_bot() is not None,
    )
    push = BilibiliPushDeliveryService(
        resources.delivery,
        resources.subscriptions,
        build_dynamic_link_message,
        build_dynamic_text_message,
        append_text_hint,
        resources.push_message_limiter,
        getattr(resources.ai, "summarize_bilibili_dynamic", None),
        settings.bilibili.push.content_max_chars,
        settings.bilibili.push.summary_max_chars,
        settings.bilibili.push.summary_use_ai,
        service.targets.can_target_query_history,
        resources.admin_notices,
        service.targets.dynamic_link_tag,
        prepend_text_hint,
        build_dynamic_images_message,
        service.targets.seer_category_uid(),
    )
    return BilibiliMonitorService(
        service,
        auth_invalid,
        push.send,
        check_second=settings.bilibili.polling.check_second,
    )
