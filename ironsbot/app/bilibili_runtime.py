# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.runtime.replies import append_text_hint, prepend_text_hint
from ironsbot.services.bilibili.delivery import BilibiliPushDeliveryService
from ironsbot.services.bilibili.runtime import BilibiliMonitorService

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.app.resources import ApplicationResources
    from ironsbot.config.models.settings import Settings
    from nonebot.adapters.onebot.v11 import Bot


def build_bilibili_monitor(
    settings: Settings,
    resources: ApplicationResources,
) -> BilibiliMonitorService:
    from ironsbot.plugins.bilibili.auth import send_bili_login_notice
    from ironsbot.plugins.bilibili.delivery import (
        build_dynamic_images_message,
        build_dynamic_link_message,
        build_dynamic_text_message,
    )

    config = settings
    delivery = resources.delivery
    admin_notices = resources.admin_notices
    bilibili_service = resources.bilibili
    bilibili_login = resources.bilibili_login
    ai_service = resources.ai
    bili_notice_sender = partial(send_bili_login_notice, admin_notices)
    bili_auth_invalid = partial(
        bilibili_login.notify_required,
        send_notice=bili_notice_sender,
        is_online=lambda: delivery.default_bot() is not None,
    )
    bili_push_delivery = BilibiliPushDeliveryService(
        delivery,
        resources.subscriptions,
        build_dynamic_link_message,
        build_dynamic_text_message,
        append_text_hint,
        resources.push_message_limiter,
        getattr(ai_service, "summarize_bilibili_dynamic", None),
        config.bilibili.push.content_max_chars,
        config.bilibili.push.summary_max_chars,
        config.bilibili.push.summary_use_ai,
        bilibili_service.targets.can_target_query_history,
        admin_notices,
        bilibili_service.targets.dynamic_link_tag,
        prepend_text_hint,
        build_dynamic_images_message,
        bilibili_service.targets.seer_category_uid(),
    )
    return BilibiliMonitorService(
        bilibili_service,
        bili_auth_invalid,
        bili_push_delivery.send,
    )


def build_bilibili_connect_hook(
    bili_monitor: BilibiliMonitorService,
) -> Callable[[Bot], Awaitable[None]]:
    async def check_bilibili_on_connect(bot: Bot) -> None:
        await bili_monitor.check_on_connect(str(bot.self_id))

    return check_bilibili_on_connect
