# SPDX-License-Identifier: MIT
"""Typed application resource bundle shared by composition and the registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.app.private_extensions import (
        PrivateExtensionCatalog,
        PrivateExtensionRuntime,
    )
    from ironsbot.core.features import FeatureService
    from ironsbot.integrations.onebot.delivery import OneBotDelivery
    from ironsbot.integrations.onebot.outbound import GroupOutboundRateLimitService
    from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
    from ironsbot.runtime.commands import CommandCatalog
    from ironsbot.services.activity.service import ActivityService
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.bilibili.login import BilibiliLoginService
    from ironsbot.services.bilibili.service import BilibiliService
    from ironsbot.services.messaging.admin_notice import AdminNoticeService
    from ironsbot.services.messaging.delivery import MessageLimiter
    from ironsbot.services.messaging.help_hint import HelpHintService
    from ironsbot.services.messaging.sendpic import SendpicService
    from ironsbot.services.messaging.service import MessagingService
    from ironsbot.services.operations.data_sync import DataSyncService
    from ironsbot.services.operations.docker_update import DockerUpdateService
    from ironsbot.services.operations.headless import HeadlessService
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
    commands: CommandCatalog
    help_hint: HelpHintService
    private_extensions: PrivateExtensionCatalog
    private_extension_runtime: PrivateExtensionRuntime
