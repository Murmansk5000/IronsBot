# SPDX-License-Identifier: MIT
"""Typed application resource bundle shared by composition and the registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.app.private_extensions import PrivateExtensionCatalog
    from ironsbot.core.command_catalog import CommandCatalog
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.plugin_install import PluginContributionCatalog
    from ironsbot.core.promotions import PromotionCatalog
    from ironsbot.integrations.onebot.help_hint import OneBotHelpHintPort
    from ironsbot.integrations.onebot.ingress_policy import OneBotIngressPolicy
    from ironsbot.integrations.qq_official.runtime import QQOfficialRuntime
    from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
    from ironsbot.services.about import AboutService
    from ironsbot.services.activity.service import ActivityService
    from ironsbot.services.ai.actions import AiIntentActionExecutor
    from ironsbot.services.ai.input_routing import AiInputRoutingService
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.bilibili.login import BilibiliLoginService
    from ironsbot.services.bilibili.runtime import BilibiliMonitorService
    from ironsbot.services.bilibili.service import BilibiliService
    from ironsbot.services.identity_link_commands import IdentityLinkCommands
    from ironsbot.services.identity_linking import IdentityLinkingService
    from ironsbot.services.identity_observation import SilentIdentityObservationService
    from ironsbot.services.messaging.addressed_input import AddressedInputHintService
    from ironsbot.services.messaging.admin_notice import AdminNoticeService
    from ironsbot.services.messaging.outbound_routing import PlatformOutboundMessenger
    from ironsbot.services.messaging.sendpic import SendpicService
    from ironsbot.services.messaging.service import MessagingService
    from ironsbot.services.operations.data_sync import DataSyncService
    from ironsbot.services.operations.docker_update import DockerUpdateService
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.operations.scheduled_restart import ScheduledRestartService
    from ironsbot.services.operations.server_status import ServerStatusService
    from ironsbot.services.operations.startup import StartupNoticeService
    from ironsbot.services.pet_config import PetConfigQueryService
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.seer.local_rank import LocalRankService
    from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowService
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.rank_page_refresh import RankPageRefreshService
    from ironsbot.services.seer.resources import SeerQueryResources
    from ironsbot.services.team.audit import TeamAuditService
    from ironsbot.services.team.resource import TeamResourceService


@dataclass(frozen=True, slots=True)
class ApplicationResources:
    about: AboutService
    query_sessions: PortableQuerySessions
    features: FeatureService
    promotions: PromotionCatalog
    admin_notices: AdminNoticeService
    activity: ActivityService
    headless: HeadlessService
    server_status: ServerStatusService
    subscriptions: PushUnsubscribeStore
    outbound_messenger: PlatformOutboundMessenger
    qq_official: QQOfficialRuntime | None
    bilibili: BilibiliService
    bilibili_login: BilibiliLoginService
    bilibili_monitor: BilibiliMonitorService
    lucky_skin_window: LuckySkinWindowService
    messaging: MessagingService
    sendpic: SendpicService
    team_audit: TeamAuditService
    team_resource: TeamResourceService
    local_rank: LocalRankService
    rank_page_refresh: RankPageRefreshService
    player_id_resolver: PlayerIdResolver
    seer: SeerQueryResources
    pet_config: PetConfigQueryService
    ai: AiService
    ai_intent_actions: AiIntentActionExecutor
    ai_input_routing: AiInputRoutingService
    ai_startup_check: Callable[[], Awaitable[None]]
    clock_startup_check: Callable[[], Awaitable[None]]
    data_sync: DataSyncService
    docker_update: DockerUpdateService
    startup_notice: StartupNoticeService
    scheduled_restart: ScheduledRestartService
    commands: CommandCatalog
    contribution_catalog: PluginContributionCatalog
    help_hint: OneBotHelpHintPort
    addressed_input_hints: AddressedInputHintService
    identity_links: IdentityLinkCommands
    identity_linking: IdentityLinkingService
    identity_observer: SilentIdentityObservationService | None
    onebot_ingress: OneBotIngressPolicy
    private_extensions: PrivateExtensionCatalog
