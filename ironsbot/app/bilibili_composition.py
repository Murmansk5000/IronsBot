# SPDX-License-Identifier: MIT
"""OneBot Bilibili monitor assembly owned by application composition."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from ironsbot.integrations.http.bilibili import (
    fetch_bili_account_name,
    fetch_bili_feed,
    poll_bili_login_qr,
    request_bili_login_qr,
)
from ironsbot.integrations.onebot.bilibili_auth import send_bili_login_notice
from ironsbot.integrations.onebot.bilibili_targets import (
    build_onebot_bili_configured_targets,
)
from ironsbot.integrations.storage.bilibili_cookie import FileBiliCookieStore
from ironsbot.integrations.storage.bilibili_history import (
    SqliteBiliDynamicHistoryStore,
)
from ironsbot.integrations.storage.bilibili_preferences import (
    SqliteBiliPushPreferenceStore,
)
from ironsbot.services.bilibili.accounts import BiliAccountNames
from ironsbot.services.bilibili.login import BilibiliLoginService
from ironsbot.services.bilibili.outbound_delivery import BilibiliDynamicOutboundSender
from ironsbot.services.bilibili.runtime import BilibiliMonitorService
from ironsbot.services.bilibili.service import BilibiliService
from ironsbot.services.bilibili.targets import BiliTargetService

if TYPE_CHECKING:
    from ironsbot.app.lifecycle import TaskOwner
    from ironsbot.config.models.settings import Settings
    from ironsbot.core.bilibili import BiliConfig
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.integrations.http.clients import HttpClients
    from ironsbot.integrations.onebot.router import BotRouter
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.messaging.admin_notice import AdminNoticeService
    from ironsbot.services.messaging.proactive_delivery import ProactiveMessageDelivery
    from ironsbot.services.messaging.subscriptions import PushSubscriptionRepository


@dataclass(frozen=True, slots=True)
class BilibiliComponents:
    """Bilibili query, history, target, and login services."""

    service: BilibiliService
    login: BilibiliLoginService


def build_onebot_bilibili_components(
    settings: Settings,
    http_clients: HttpClients,
    features: FeatureService,
    subscriptions: PushSubscriptionRepository,
    task_owner: TaskOwner,
) -> BilibiliComponents:
    """Build Bilibili services and compile OneBot-specific configured targets."""
    data_dir = settings.bilibili.storage.data_dir
    cookie_store = FileBiliCookieStore(data_dir / "bili_cookie_cache.txt")
    service = BilibiliService(
        config=settings.bilibili,
        targets=BiliTargetService(
            settings.bilibili,
            features,
            build_onebot_bili_configured_targets(
                settings.bilibili,
                settings.onebot_references,
            ),
            SqliteBiliPushPreferenceStore(settings.paths.qq_state),
            subscriptions,
            BiliAccountNames(partial(fetch_bili_account_name, http_clients.origin)),
        ),
        cookie_store=cookie_store,
        history=SqliteBiliDynamicHistoryStore(
            data_dir / "dynamic_history.sqlite",
            settings.bilibili.storage.history_max_items,
        ),
        fetch_feed=partial(fetch_bili_feed, http_clients.origin),
    )
    return BilibiliComponents(
        service=service,
        login=BilibiliLoginService(
            settings.bilibili.login_notice_cooldown_seconds,
            cookie_store,
            request_qr=partial(request_bili_login_qr, http_clients.origin),
            poll_qr=partial(poll_bili_login_qr, http_clients.origin),
            spawn=task_owner.create,
        ),
    )


def build_onebot_bilibili_monitor(  # noqa: PLR0913 - composition root
    *,
    service: BilibiliService,
    login: BilibiliLoginService,
    subscriptions: PushSubscriptionRepository,
    admin_notices: AdminNoticeService,
    bot_router: BotRouter,
    proactive_delivery: ProactiveMessageDelivery,
    ai_service: AiService,
    config: BiliConfig,
) -> BilibiliMonitorService:
    """Assemble OneBot configuration with a platform-neutral push sender."""
    notice_sender = partial(send_bili_login_notice, admin_notices)
    auth_invalid = partial(
        login.notify_required,
        send_notice=notice_sender,
        is_online=lambda: bot_router.default_bot() is not None,
    )
    push_delivery = BilibiliDynamicOutboundSender(
        proactive_delivery,
        subscriptions,
        getattr(ai_service, "summarize_bilibili_dynamic", None),
        config.push.content_max_chars,
        config.push.summary_max_chars,
        config.push.summary_use_ai,
        service.targets.can_conversation_query_history,
        admin_notices,
        lambda uid: service.targets.category_config_for_uid(uid) is not None,
    )
    return BilibiliMonitorService(service, auth_invalid, push_delivery.send)
