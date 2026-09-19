# SPDX-License-Identifier: MIT
"""Compose cross-feature runtime dependencies for the current OneBot host."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.config.models.features import build_feature_service
from ironsbot.core.platform import Platform
from ironsbot.core.promotions import PromotionCatalog
from ironsbot.integrations.onebot.matchers import PromptSessionManager
from ironsbot.integrations.onebot.outbound import (
    GroupOutboundRateLimitService,
    install_outbound_rate_limit_hooks,
)
from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
from ironsbot.integrations.onebot.router import BotRouter
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.services.messaging.admin_notice import AdminNoticeService
from ironsbot.services.messaging.admin_notice_delivery import OutboundAdminNoticeSender
from ironsbot.services.messaging.outbound_routing import PlatformOutboundMessenger
from ironsbot.services.messaging.proactive_delivery import (
    ProactiveDeliveryPolicy,
    ProactiveMessageDelivery,
)

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import AsyncClient

    from ironsbot.app.lifecycle import TaskOwner
    from ironsbot.config.models.settings import Settings
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.outbound import OutboundMessenger
    from ironsbot.integrations.qq_official.runtime import QQOfficialRuntime


@dataclass(frozen=True, slots=True)
class CommonComponents:
    """Shared runtime dependencies constructed once per application process."""

    prompt_sessions: PromptSessionManager
    features: FeatureService
    promotions: PromotionCatalog
    outbound: GroupOutboundRateLimitService
    subscriptions: PushUnsubscribeStore
    bot_router: BotRouter
    outbound_messenger: PlatformOutboundMessenger
    qq_official: QQOfficialRuntime | None
    proactive_delivery: ProactiveMessageDelivery
    admin_notices: AdminNoticeService


def build_common_components(
    settings: Settings,
    task_owner: TaskOwner,
    *,
    http_client: AsyncClient,
    cache_root: Path,
) -> CommonComponents:
    """Build policy, push delivery, and shared interaction primitives."""
    features = build_feature_service(
        settings.features,
        settings.bot.superusers,
        command_features=settings.messaging.command_feature_keys,
        schedule_features=settings.messaging.schedule_feature_keys,
        qq_official=(
            settings.bot.qq_official
            if settings.bot.qq_official.enabled_accounts
            else None
        ),
        references=settings.platform_references,
    )
    for target in settings.identities.users.values():
        if target.qq is None:
            continue
        for alias, openid in target.official.items():
            account = settings.bot.qq_official.enabled_accounts.get(alias)
            if account is not None:
                features.register_identity_link(
                    official_app_id=account.app_id,
                    official_openid=openid,
                    onebot_qq_id=str(target.qq),
                )
    outbound = GroupOutboundRateLimitService(
        settings.messaging.outbound_rate_limit,
        features,
        task_owner.create,
    )
    subscriptions = PushUnsubscribeStore(settings.paths.qq_state)
    bot_router = BotRouter(
        settings.messaging.bot_routing,
        settings.onebot_references,
    )
    promotions = PromotionCatalog(settings.promotions)
    platform_selection = settings.outbound_platform_selection
    platform_messengers: dict[Platform, OutboundMessenger] = {
        Platform.ONEBOT: OneBotOutboundMessenger(
            bot_router,
            outbound,
            enabled=platform_selection.onebot_outbound_enabled,
        ),
    }
    qq_official = None
    if settings.bot.qq_official.enabled_accounts:
        _configure_qq_sdk_api(sandbox=settings.bot.qq_official.sandbox)
        try:
            from ironsbot.integrations.qq_official.outbound_messenger import (
                QQOfficialOutboundMessenger,
            )
            from ironsbot.integrations.qq_official.runtime import (
                QQOfficialRuntime,
                QQOfficialRuntimeAccount,
            )
        except ModuleNotFoundError as error:
            msg = (
                "QQ Official Bot is enabled, but qqbot-agent-sdk is missing; "
                "install IronsBot with the qq-official extra"
            )
            raise RuntimeError(msg) from error

        qq_official = QQOfficialRuntime(
            tuple(
                QQOfficialRuntimeAccount(
                    account.app_id,
                    account.secret,
                    required=account.required,
                    custom_keyboards=account.custom_keyboards,
                    label=alias,
                )
                for alias, account in settings.bot.qq_official.enabled_accounts.items()
            ),
            http_client=http_client,
            session_root=cache_root / "qq_official",
            startup_timeout_seconds=settings.bot.qq_official.startup_timeout_seconds,
        )

        platform_messengers[Platform.QQ_OFFICIAL] = QQOfficialOutboundMessenger(
            {
                account.app_id: account.proactive_messages
                for account in settings.bot.qq_official.enabled_accounts.values()
            },
            bot_provider=qq_official.sender,
            account_custom_keyboards={
                account.app_id: account.custom_keyboards
                for account in settings.bot.qq_official.enabled_accounts.values()
            },
        )
    outbound_messenger = PlatformOutboundMessenger(platform_messengers)
    proactive_delivery = ProactiveMessageDelivery(
        outbound_messenger,
        features,
        promotions,
        subscriptions,
        settings.messaging.push_unsubscribe,
        ProactiveDeliveryPolicy(
            max_attempts=settings.messaging.proactive_delivery.max_attempts,
            max_parallel_targets=(
                settings.messaging.proactive_delivery.max_parallel_targets
            ),
            retry_batch_divisor=(
                settings.messaging.proactive_delivery.retry_batch_divisor
            ),
            retry_delay_seconds=(
                settings.messaging.proactive_delivery.retry_delay_seconds
            ),
        ),
    )
    install_outbound_rate_limit_hooks(outbound)
    return CommonComponents(
        prompt_sessions=PromptSessionManager(),
        features=features,
        promotions=promotions,
        outbound=outbound,
        subscriptions=subscriptions,
        bot_router=bot_router,
        outbound_messenger=outbound_messenger,
        qq_official=qq_official,
        proactive_delivery=proactive_delivery,
        admin_notices=AdminNoticeService(
            features,
            OutboundAdminNoticeSender(proactive_delivery),
        ),
    )


def _configure_qq_sdk_api(*, sandbox: bool) -> None:
    os.environ["QQ_API_BASE"] = (
        "https://sandbox.api.sgroup.qq.com"
        if sandbox
        else "https://api.sgroup.qq.com"
    )
