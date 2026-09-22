# SPDX-License-Identifier: MIT
"""OneBot Bilibili monitor assembly owned by application composition."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from ironsbot.integrations.configured_targets.bilibili import (
    build_bili_configured_targets,
)
from ironsbot.integrations.http.bilibili import (
    fetch_bili_account_name,
    fetch_bili_dynamic_detail,
    fetch_bili_feed,
    poll_bili_login_qr,
    request_bili_login_qr,
)
from ironsbot.integrations.image_collage import (
    fetch_collage_image,
    render_adaptive_collage,
)
from ironsbot.integrations.storage.bilibili_cookie import FileBiliCookieStore
from ironsbot.integrations.storage.bilibili_delivery_ledger import (
    SqliteDynamicDeliveryLedger,
)
from ironsbot.integrations.storage.bilibili_history import (
    SqliteBiliDynamicHistoryStore,
)
from ironsbot.integrations.storage.bilibili_preferences import (
    SqliteBiliPushPreferenceStore,
)
from ironsbot.services.bilibili.accounts import BiliAccountNames
from ironsbot.services.bilibili.content import DynamicContentCompactor
from ironsbot.services.bilibili.delivery_recovery import BiliStartupRecovery
from ironsbot.services.bilibili.login import BilibiliLoginService
from ironsbot.services.bilibili.login_notice import send_bili_login_notice
from ironsbot.services.bilibili.outbound_delivery import BilibiliDynamicOutboundSender
from ironsbot.services.bilibili.private_routes import BiliPrivateRoutes
from ironsbot.services.bilibili.runtime import BilibiliMonitorService
from ironsbot.services.bilibili.service import BilibiliService
from ironsbot.services.bilibili.targets import BiliTargetService
from ironsbot.services.messaging.image_collage import ImageCollageService

if TYPE_CHECKING:
    from ironsbot.app.lifecycle import TaskOwner
    from ironsbot.config.models.settings import Settings
    from ironsbot.core.bilibili import BiliConfig
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.integrations.http.clients import HttpClients
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.identity_principals import IdentityPrincipalService
    from ironsbot.services.messaging.admin_notice import AdminNoticeService
    from ironsbot.services.messaging.proactive_delivery import ProactiveMessageDelivery
    from ironsbot.services.messaging.subscriptions import PushSubscriptionRepository


@dataclass(frozen=True, slots=True)
class BilibiliComponents:
    """Bilibili query, history, target, and login services."""

    service: BilibiliService
    login: BilibiliLoginService
    preferences: SqliteBiliPushPreferenceStore


def build_bilibili_components(  # noqa: PLR0913 - explicit composition dependencies
    settings: Settings,
    http_clients: HttpClients,
    features: FeatureService,
    subscriptions: PushSubscriptionRepository,
    task_owner: TaskOwner,
    identity_principals: IdentityPrincipalService,
    private_routes: BiliPrivateRoutes | None = None,
) -> BilibiliComponents:
    """Build Bilibili services and compile configured delivery targets."""
    data_dir = settings.bilibili.storage.data_dir
    cookie_store = FileBiliCookieStore(data_dir / "bili_cookie_cache.txt")
    preferences = SqliteBiliPushPreferenceStore(
        settings.paths.qq_state,
        principal_for=identity_principals.conversation_principal,
    )
    routes = private_routes or _private_routes(settings)
    service = BilibiliService(
        config=settings.bilibili,
        targets=BiliTargetService(
            settings.bilibili,
            features,
            build_bili_configured_targets(
                settings.bilibili,
                settings.platform_references,
            ),
            preferences,
            subscriptions,
            BiliAccountNames(partial(fetch_bili_account_name, http_clients.origin)),
            private_routes=routes,
        ),
        cookie_store=cookie_store,
        history=SqliteBiliDynamicHistoryStore(
            data_dir / "dynamic_history.sqlite",
            settings.bilibili.storage.history_max_items,
        ),
        fetch_feed=partial(fetch_bili_feed, http_clients.origin),
        fetch_detail=partial(fetch_bili_dynamic_detail, http_clients.origin),
        spawn=task_owner.create,
        image_collage=ImageCollageService(
            partial(fetch_collage_image, http_clients.origin), render_adaptive_collage
        ),
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
        preferences=preferences,
    )


def _private_routes(settings: Settings) -> BiliPrivateRoutes:
    accounts = settings.bot.qq_official.enabled_accounts
    default = accounts.get(settings.bot.qq_official.resolved_default_account or "")
    return BiliPrivateRoutes(
        onebot_enabled=settings.outbound_platform_selection.onebot_outbound_enabled,
        official_accounts=frozenset(account.app_id for account in accounts.values()),
        default_account=None if default is None else default.app_id,
    )


def build_bilibili_monitor(  # noqa: PLR0913 - composition root
    *,
    service: BilibiliService,
    login: BilibiliLoginService,
    subscriptions: PushSubscriptionRepository,
    admin_notices: AdminNoticeService,
    proactive_delivery: ProactiveMessageDelivery,
    ai_service: AiService,
    config: BiliConfig,
) -> BilibiliMonitorService:
    """Assemble monitoring with platform-neutral notice and push delivery."""
    notice_sender = partial(send_bili_login_notice, admin_notices)
    auth_invalid = partial(
        login.notify_required,
        send_notice=notice_sender,
    )
    compactor = DynamicContentCompactor(
        getattr(ai_service, "summarize_bilibili_dynamic", None),
        config.push.content_max_chars,
        config.push.summary_max_chars,
        config.push.summary_use_ai,
    )
    service.content_compactor = compactor
    push_delivery = BilibiliDynamicOutboundSender(
        delivery=proactive_delivery,
        subscriptions=subscriptions,
        content_compactor=compactor,
        history=service.history,
        can_query_history=service.targets.can_conversation_query_history,
        admin_notices=admin_notices,
        has_category_subscriptions=(
            lambda uid: service.targets.category_config_for_uid(uid) is not None
        ),
        account_name=service.targets.account_display_name,
        image_collage=service.image_collage,
        combine_images=config.push.combine_images,
        ledger=SqliteDynamicDeliveryLedger(
            Path(config.storage.data_dir) / "delivery_stages.sqlite"
        ),
        category_labels=lambda uid, keys: tuple(
            definition.label
            if (category_config := service.targets.category_config_for_uid(uid))
            is not None
            and (definition := category_config.categories.get(key)) is not None
            else key
            for key in keys
        ),
    )
    return BilibiliMonitorService(
        service,
        auth_invalid,
        push_delivery.send,
        startup_recovery=BiliStartupRecovery(push_delivery, service.targets),
    )
