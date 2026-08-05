# SPDX-License-Identifier: MIT
"""Typed application resource bundle shared by composition and the registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.app.private_extensions import (
        PrivateExtensionCatalog,
        PrivateExtensionRuntime,
    )
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.promotions import PromotionCatalog
    from ironsbot.integrations.onebot.delivery import (
        MessageLimiter,
        OneBotDelivery,
    )
    from ironsbot.integrations.onebot.outbound import GroupOutboundRateLimitService
    from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
    from ironsbot.runtime.commands import CommandCatalog
    from ironsbot.runtime.onebot_help_hint import OneBotHelpHintPort
    from ironsbot.runtime.plugins import PluginContributionCatalog
    from ironsbot.services.activity.service import ActivityService
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.bilibili.login import BilibiliLoginService
    from ironsbot.services.bilibili.runtime import BilibiliMonitorService
    from ironsbot.services.bilibili.service import BilibiliService
    from ironsbot.services.messaging.admin_notice import AdminNoticeService
    from ironsbot.services.messaging.sendpic import SendpicService
    from ironsbot.services.messaging.service import MessagingService
    from ironsbot.services.operations.data_sync import DataSyncService
    from ironsbot.services.operations.docker_update import DockerUpdateService
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.operations.scheduled_restart import ScheduledRestartService
    from ironsbot.services.operations.server_status import ServerStatusService
    from ironsbot.services.operations.startup import StartupNoticeService
    from ironsbot.services.pet_config import PetConfigQueryService
    from ironsbot.services.seer.local_rank import LocalRankService
    from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowService
    from ironsbot.services.seer.rank_page_refresh import RankPageRefreshService
    from ironsbot.services.seer.resources import SeerQueryResources
    from ironsbot.services.team.audit import TeamAuditService
    from ironsbot.services.team.resource import TeamResourceService


@dataclass(frozen=True, slots=True)
class ApplicationResources:
    features: FeatureService
    promotions: PromotionCatalog
    outbound: GroupOutboundRateLimitService
    delivery: OneBotDelivery
    push_message_limiter: MessageLimiter
    admin_notices: AdminNoticeService
    activity: ActivityService
    headless: HeadlessService
    server_status: ServerStatusService
    subscriptions: PushUnsubscribeStore
    bilibili: BilibiliService
    bilibili_login: BilibiliLoginService
    bilibili_monitor: BilibiliMonitorService
    bilibili_content_renderer: Callable[[dict[str, Any], str | None], Any | None]
    lucky_skin_window: LuckySkinWindowService
    messaging: MessagingService
    sendpic: SendpicService
    team_audit: TeamAuditService
    team_resource: TeamResourceService
    local_rank: LocalRankService
    rank_page_refresh: RankPageRefreshService
    seer: SeerQueryResources
    pet_config: PetConfigQueryService
    ai: AiService
    data_sync: DataSyncService
    docker_update: DockerUpdateService
    startup_notice: StartupNoticeService
    scheduled_restart: ScheduledRestartService
    commands: CommandCatalog
    contribution_catalog: PluginContributionCatalog
    help_hint: OneBotHelpHintPort
    private_extensions: PrivateExtensionCatalog
    private_extension_runtime: PrivateExtensionRuntime
