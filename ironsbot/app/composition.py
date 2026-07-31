# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

from ironsbot.app.file_logging import FileLogging
from ironsbot.app.lifecycle import ApplicationLifecycle, TaskOwner
from ironsbot.app.private_extensions import (
    PrivateExtensionCatalog,
    PrivateExtensionRuntime,
    load_private_extension_catalog,
)
from ironsbot.app.registry import build_plugin_registry
from ironsbot.core.features import Feature, FeatureService
from ironsbot.integrations.db_registry import DatabaseManager
from ironsbot.integrations.db_sync.runner import DatabaseSync
from ironsbot.integrations.docker.client import DockerClient
from ironsbot.integrations.headless_seer.client import ClientManager
from ironsbot.integrations.headless_seer.rank import fetch_rank_page
from ironsbot.integrations.htmlkit import render_html_template
from ironsbot.integrations.http.activity_notice import UnityNoticeSource
from ironsbot.integrations.http.ai import HttpAiCompletionClient
from ironsbot.integrations.http.bilibili import (
    fetch_bili_account_name,
    fetch_bili_feed,
    poll_bili_login_qr,
    request_bili_login_qr,
)
from ironsbot.integrations.http.clients import HttpClients
from ironsbot.integrations.http.seer_images import HttpSeerImageSource
from ironsbot.integrations.http.server_notice import HttpServerNoticeSource
from ironsbot.integrations.onebot.delivery import OneBotDelivery
from ironsbot.integrations.onebot.group_probe import OneBotGroupProbe
from ironsbot.integrations.onebot.outbound import (
    GroupOutboundRateLimitService,
    install_outbound_rate_limit_hooks,
)
from ironsbot.integrations.onebot.promotions import append_fire_manual_ad_for_target
from ironsbot.integrations.onebot.router import BotRouter
from ironsbot.integrations.process import terminate_bot_process
from ironsbot.integrations.scheduler.facade import SchedulerFacade
from ironsbot.integrations.seer_data.database import SeerDatabase
from ironsbot.integrations.sendpic import SendpicBackendProvider
from ironsbot.integrations.storage.achievement_history import (
    SqliteAchievementHistoryStore,
)
from ironsbot.integrations.storage.activity import ActivitySentStore
from ironsbot.integrations.storage.ai_memory import SqliteAiMemoryStore
from ironsbot.integrations.storage.bilibili_cookie import FileBiliCookieStore
from ironsbot.integrations.storage.bilibili_history import (
    SqliteBiliDynamicHistoryStore,
)
from ironsbot.integrations.storage.bilibili_preferences import (
    SqliteBiliPushPreferenceStore,
)
from ironsbot.integrations.storage.local_rank import SqliteLocalRankRepository
from ironsbot.integrations.storage.pet_config_images import (
    FilePetConfigImageStore,
)
from ironsbot.integrations.storage.player_bindings import (
    SqlitePlayerBindingStore,
)
from ironsbot.integrations.storage.player_query_limits import (
    SqlitePlayerQueryLimitStore,
)
from ironsbot.integrations.storage.push_subscriptions import (
    PushUnsubscribeStore,
)
from ironsbot.integrations.storage.rank_display import SqliteRankDisplayStore
from ironsbot.integrations.storage.rank_page_cache import SqliteRankPageCache
from ironsbot.integrations.storage.render_cache import FileRenderCache
from ironsbot.integrations.storage.team_audit import SqliteTeamAuditReminderStore
from ironsbot.integrations.storage.team_resources import (
    TeamResourceSubscriptionStore,
)
from ironsbot.runtime.commands import CommandCatalog, CommandContext
from ironsbot.runtime.in_flight_requests import InFlightRequestService
from ironsbot.runtime.matchers import MatcherRegistry, PromptSessionManager
from ironsbot.runtime.priority import AdminPriorityService
from ironsbot.services.activity.delivery import (
    ActivityReminderDelivery,
    ActivityReminderTargets,
)
from ironsbot.services.activity.models import ActivityInfoCache
from ironsbot.services.activity.repository import ActivityRepository
from ironsbot.services.activity.service import (
    ACTIVITY_PUSH_SUBSCRIPTION_KEY,
    ActivityService,
    TargetType,
)
from ironsbot.services.ai.service import AiService
from ironsbot.services.bilibili.accounts import BiliAccountNames
from ironsbot.services.bilibili.login import BilibiliLoginService
from ironsbot.services.bilibili.service import BilibiliService
from ironsbot.services.bilibili.targets import BiliTargetService
from ironsbot.services.messaging.admin_notice import AdminNoticeService
from ironsbot.services.messaging.command_cooldown import CommandCooldownService
from ironsbot.services.messaging.help_hint import HelpHintService
from ironsbot.services.messaging.sendpic import SendpicService
from ironsbot.services.messaging.subscriptions import (
    ACTIVITY_LEAD_HOURS_PREFERENCE,
)
from ironsbot.services.operations.data_sync import DataSyncService
from ironsbot.services.operations.docker_preflight import DockerStartupPreflightStore
from ironsbot.services.operations.docker_update import DockerUpdateService
from ironsbot.services.operations.headless import HeadlessService
from ironsbot.services.operations.headless_session import HeadlessSessionFactory
from ironsbot.services.operations.server_status import ServerStatusService
from ironsbot.services.operations.startup import StartupNoticeService
from ironsbot.services.pet_config import PetConfigQueryService
from ironsbot.services.seer.achievement_history import AchievementHistoryService
from ironsbot.services.seer.autocard import AutocardService
from ironsbot.services.seer.battle_effect import BattleEffectQueryService
from ironsbot.services.seer.countermark_stat_rank import CountermarkStatRankService
from ironsbot.services.seer.data_queries import SeerDataQueryService
from ironsbot.services.seer.equipment import EquipmentQueryService
from ironsbot.services.seer.local_rank import LocalRankService
from ironsbot.services.seer.mintmark import MintmarkQueryService
from ironsbot.services.seer.peak import PeakQueryService
from ironsbot.services.seer.pet_query import PetQueryService
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_query_limits import PlayerQueryQuotaService
from ironsbot.services.seer.player_request_protection import (
    PlayerRequestProtectionService,
)
from ironsbot.services.seer.player_service import (
    PlayerDetailService,
    PlayerService,
)
from ironsbot.services.seer.rank import RankService
from ironsbot.services.seer.rank_admin import (
    RankAdminPolicy,
    RankAdminService,
)
from ironsbot.services.seer.rank_display import RankDisplayService
from ironsbot.services.seer.rank_page_refresh import RankPageRefreshService
from ironsbot.services.seer.rank_queries import (
    RankQueryPolicy,
    RankQueryService,
)
from ironsbot.services.seer.rendering.custom_pet_info import (
    render_custom_pet_info,
)
from ironsbot.services.seer.rendering.peak_pet_rank import render_peak_pet_rank
from ironsbot.services.seer.rendering.peak_pool import render_peak_pool
from ironsbot.services.seer.rendering.peak_pool_vote import render_peak_pool_vote
from ironsbot.services.seer.rendering.type_matchup import render_type_matchup
from ironsbot.services.seer.resources import SeerQueryResources
from ironsbot.services.seer.team import SeerTeamQueryService
from ironsbot.services.seer.type_query import TypeQueryService
from ironsbot.services.team.audit import TeamAuditService
from ironsbot.services.team.resource import TeamResourceService

if TYPE_CHECKING:
    from nonebot.internal.driver import Driver

    from ironsbot.config.models.activity import ActivityConfig
    from ironsbot.config.models.settings import Settings
    from ironsbot.runtime.plugins import PluginDefinition
    from ironsbot.services.messaging.delivery import (
        MessageDelivery,
        MessageLimiter,
    )
    from ironsbot.services.messaging.service import MessagingService

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
SEERAPI_DB_NAME = "seerapi"
ACTIVITY_INFO_CACHE_TTL = timedelta(seconds=60)
SOON_ENDING_THRESHOLD = timedelta(days=7)
@dataclass(frozen=True, slots=True)
class ApplicationResources:
    features: FeatureService
    outbound: GroupOutboundRateLimitService
    delivery: MessageDelivery
    push_message_limiter: MessageLimiter
    admin_notices: AdminNoticeService
    activity: ActivityService
    headless: HeadlessService
    server_status: ServerStatusService
    priority: AdminPriorityService
    subscriptions: PushUnsubscribeStore
    bilibili: BilibiliService
    bilibili_login: BilibiliLoginService
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


@dataclass(slots=True)
class Application:
    settings: Settings
    driver: Driver
    asgi: Any
    scheduler: SchedulerFacade
    file_logging: FileLogging
    http_clients: HttpClients
    databases: DatabaseManager
    prompt_sessions: PromptSessionManager
    resources: ApplicationResources
    plugins: tuple[PluginDefinition, ...]
    matchers: MatcherRegistry
    lifecycle: ApplicationLifecycle
    _installed: bool = field(default=False, init=False)

    def install(self) -> None:
        if self._installed:
            return
        for plugin in self.plugins:
            if plugin.install is not None:
                plugin.install(self.matchers)
        self.matchers.validate_command_catalog(self.resources.commands)
        self.matchers.install_postprocessor()
        self.lifecycle.install()
        self._installed = True


def _build_activity_service(  # noqa: PLR0913 - composition root
    config: ActivityConfig,
    features: FeatureService,
    message_delivery: MessageDelivery,
    databases: DatabaseManager,
    subscriptions: PushUnsubscribeStore,
    notice_source: UnityNoticeSource,
    message_limiter: MessageLimiter,
) -> ActivityService:
    sent_store = ActivitySentStore(config.cache_path)
    repository = ActivityRepository()

    def load_rows():
        with databases.session(SEERAPI_DB_NAME) as session:
            return repository.load(session, only_shown=config.only_shown)

    def preference_values():
        return (
            preference.value
            for preference in subscriptions.all_time_preferences(
                subscription_key=ACTIVITY_PUSH_SUBSCRIPTION_KEY,
                preference_type=ACTIVITY_LEAD_HOURS_PREFERENCE,
            )
        )

    def preference_for_target(
        target_type: TargetType,
        target_id: int,
    ) -> str | None:
        return subscriptions.get_time_preference(
            target_type,
            target_id,
            ACTIVITY_PUSH_SUBSCRIPTION_KEY,
            ACTIVITY_LEAD_HOURS_PREFERENCE,
        )

    def targets() -> ActivityReminderTargets:
        return ActivityReminderTargets(
            group_ids=tuple(
                features.groups_for_feature(ACTIVITY_PUSH_SUBSCRIPTION_KEY)
            ),
            private_user_ids=tuple(
                features.users_with_superusers(
                    features.users_for_feature(ACTIVITY_PUSH_SUBSCRIPTION_KEY)
                )
            ),
        )

    async def broadcast(reminder: ActivityReminderDelivery) -> bool:
        summary = await message_delivery.broadcast(
            reminder.message,
            group_ids=reminder.group_ids,
            private_user_ids=reminder.private_user_ids,
            action_name=reminder.action_name,
            interval_seconds=1.2,
            message_limiter=message_limiter,
            subscription_key=ACTIVITY_PUSH_SUBSCRIPTION_KEY,
        )
        return bool(summary.succeeded)

    return ActivityService(
        config=config,
        cache=ActivityInfoCache(),
        load_rows=load_rows,
        load_notice_text=notice_source.fetch,
        cache_ttl=ACTIVITY_INFO_CACHE_TTL,
        soon_ending_threshold=SOON_ENDING_THRESHOLD,
        filter_unsent=sent_store.filter_unsent,
        mark_sent=sent_store.mark_sent,
        preference_values=preference_values,
        preference_for_target=preference_for_target,
        targets=targets,
        broadcast=broadcast,
        now=lambda: datetime.now(LOCAL_TZ),
    )


def build_application(settings: Settings) -> Application:  # noqa: PLR0915
    from ironsbot.services.messaging.service import MessagingService

    driver = nonebot.get_driver()
    driver.register_adapter(OneBotV11Adapter)
    scheduler = SchedulerFacade()
    file_logging = FileLogging.create(settings.bot.logging, settings.paths)
    http_clients = HttpClients()
    databases = DatabaseManager()
    database_sync = DatabaseSync(databases)
    task_owner = TaskOwner()
    for name, source in settings.operations.data_sync.sources.items():
        database_sync.register(name, source)
    data_sync = DataSyncService(settings.operations.data_sync, database_sync)
    seer_database = SeerDatabase(
        databases,
        merge_connected_mintmarks=settings.seer.mintmark.merge_connected,
    )
    achievement_history = AchievementHistoryService(
        seer_database,
        SqliteAchievementHistoryStore(
            settings.seer.achievement_history.path,
            max_snapshots=settings.seer.achievement_history.max_snapshots,
            baseline_lookback_days=(
                settings.seer.achievement_history.baseline_lookback_days
            ),
        ),
    )
    databases.add_load_listener(
        SEERAPI_DB_NAME,
        achievement_history.capture_current_snapshot,
    )
    prompt_sessions = PromptSessionManager()
    features = FeatureService(
        settings.features,
        settings.superuser_ids,
        command_features=settings.messaging.command_feature_keys,
        schedule_features=settings.messaging.schedule_feature_keys,
    )
    outbound = GroupOutboundRateLimitService(
        settings.messaging.outbound_rate_limit,
        features,
        task_owner.create,
    )
    subscriptions = PushUnsubscribeStore(
        settings.messaging.push_unsubscribe.data_path
    )
    delivery = OneBotDelivery(
        outbound,
        settings.messaging.push_unsubscribe,
        BotRouter(
            settings.messaging.bot_routing,
            settings.onebot_references,
        ),
        subscriptions,
    )
    push_message_limiter = partial(append_fire_manual_ad_for_target, features)
    admin_notices = AdminNoticeService(features, delivery)
    install_outbound_rate_limit_hooks(outbound)

    activity = _build_activity_service(
        settings.activity,
        features,
        delivery,
        databases,
        subscriptions,
        UnityNoticeSource(
            http_clients.origin,
            settings.activity.notice_timeout_seconds,
        ),
        push_message_limiter,
    )
    headless = HeadlessService(
        ClientManager(task_owner.create),
        settings.operations.headless,
        settings.operations.headless_notice,
        admin_notices,
        request_interval_seconds=(
            settings.seer.player.request_protection.base_request_interval_seconds
            if settings.seer.player.request_protection.enabled
            else 0.0
        ),
    )
    headless_sessions = HeadlessSessionFactory(
        lambda: ClientManager(task_owner.create),
        settings.operations.headless,
        request_interval_seconds=(
            settings.seer.player.request_protection.base_request_interval_seconds
            if settings.seer.player.request_protection.enabled
            else 0.0
        ),
    )
    priority = AdminPriorityService(settings.features.priority, features)
    bili_data_dir = settings.bilibili.storage.data_dir
    bili_cookie_store = FileBiliCookieStore(
        bili_data_dir / "bili_cookie_cache.txt"
    )
    bilibili = BilibiliService(
        config=settings.bilibili,
        targets=BiliTargetService(
            settings.bilibili,
            features,
            SqliteBiliPushPreferenceStore(
                bili_data_dir / "push_preferences.sqlite"
            ),
            subscriptions,
            BiliAccountNames(
                partial(fetch_bili_account_name, http_clients.origin)
            ),
        ),
        cookie_store=bili_cookie_store,
        history=SqliteBiliDynamicHistoryStore(
            bili_data_dir / "dynamic_history.sqlite",
            settings.bilibili.storage.history_max_items,
        ),
        fetch_feed=partial(fetch_bili_feed, http_clients.origin),
    )
    bilibili_login = BilibiliLoginService(
        settings.bilibili.login_notice_cooldown_seconds,
        bili_cookie_store,
        request_qr=partial(request_bili_login_qr, http_clients.origin),
        poll_qr=partial(poll_bili_login_qr, http_clients.origin),
        spawn=task_owner.create,
    )
    messaging = MessagingService(
        settings.messaging,
        settings.activity,
        subscriptions,
        features,
        delivery,
        bilibili.targets.subscription_options,
        _push_message_limiter=push_message_limiter,
        _prepare_extra_push_options=bilibili.targets.prepare_account_names,
    )
    sendpic = SendpicService(
        settings.messaging.sendpic,
        SendpicBackendProvider(
            http_clients.cache,
            cnb_token=settings.messaging.sendpic.cnb_token,
            cnb_repo=settings.messaging.sendpic.cnb_repo,
            local_root=settings.messaging.sendpic.local_root,
        ),
    )
    team_resource = TeamResourceService(
        settings.seer.team_resource,
        TeamResourceSubscriptionStore(
            settings.seer.team_resource.subscription_path
        ),
        headless,
        settings.onebot_references,
        features,
        delivery,
    )
    team_audit = TeamAuditService(
        settings.messaging.team_audit_welcome,
        SqliteTeamAuditReminderStore(
            settings.messaging.team_audit_welcome.followup_cache_path
        ),
        features,
        delivery,
        OneBotGroupProbe(),
    )
    rank = RankService(
        settings.seer.rank,
        SqliteRankPageCache(
            settings.seer.rank.page_cache_path,
            enabled=settings.seer.rank.page_cache,
            ttl_seconds=settings.seer.rank.page_cache_ttl_seconds,
            allow_stale=settings.seer.rank.allow_stale_cache,
        ),
        seer_database.peak_season_start,
        fetch_rank_page,
    )
    seer_images = HttpSeerImageSource(http_clients)
    render_cache = FileRenderCache(
        settings.paths.render_cache,
        settings.seer.render.cache_max_size_mb * 1024 * 1024,
        db_version_getter=seer_database.version,
    )
    player_bindings = SqlitePlayerBindingStore(
        settings.seer.player.binding.path
    )
    player_query_quotas = PlayerQueryQuotaService(
        settings.seer.player.query_limits,
        player_bindings,
        features,
        SqlitePlayerQueryLimitStore(settings.seer.player.query_limits.path),
    )
    player_requests = PlayerRequestProtectionService(
        settings.seer.player.request_protection,
        features,
        headless,
        task_owner.create,
    )
    headless.add_state_listener(player_requests.on_headless_state_change)
    pet_config = PetConfigQueryService(
        seer_database,
        FilePetConfigImageStore(settings.pet_config.image_dir),
    )
    local_rank = LocalRankService(
        SqliteLocalRankRepository(
            settings.seer.local_rank.path,
            settings.seer.local_rank.max_players,
        ),
        settings.seer.local_rank,
        settings.seer.player,
        rank,
        player_requests,
    )
    rank_display = RankDisplayService(
        settings.seer.rank,
        settings.onebot_references,
        SqliteRankDisplayStore(settings.seer.rank.display_limit_path),
    )
    rank_page_refresh = RankPageRefreshService(
        settings.seer.rank.page_refresh,
        rank,
        player_requests,
    )
    player = PlayerService(
        settings.seer,
        headless,
        player_bindings,
        seer_database.error_message,
        PlayerDetailService(
            settings.seer,
            rank,
            local_rank,
            task_owner.create,
            player_requests,
        ),
        player_query_quotas,
        player_requests,
    )
    docker_client = DockerClient()
    private_extensions = load_private_extension_catalog(
        settings.operations.private_extensions
    )
    player_detail_extensions = PlayerDetailExtensionRegistry()
    rank_queries = RankQueryService(
        rank,
        local_rank,
        rank_display,
        headless,
        RankQueryPolicy(
            player_error=player.format_error,
            player_timeout_seconds=(
                settings.seer.player.detail_timeout_seconds
            ),
        ),
        player_query_quotas,
        player_requests,
    )
    rank_admin = RankAdminService(
        RankAdminPolicy(
            rank_limit=settings.seer.rank.limit,
            batch_limit=settings.seer.local_rank.batch_limit,
            refresh_limit=settings.seer.local_rank.refresh_limit,
            refresh_max_age_hours=(
                settings.seer.local_rank.refresh_max_age_hours
            ),
            page_cache_ttl_seconds=(
                settings.seer.rank.page_cache_ttl_seconds
            ),
            display_limit=rank_display.limit_for_group,
        ),
        rank,
        local_rank,
        rank_page_refresh,
        headless,
    )
    seer = SeerQueryResources(
        SeerDataQueryService(
            seer_database,
            seer_images,
            settings.seer.season,
            achievement_history,
        ),
        CountermarkStatRankService(seer_database),
        AutocardService(seer_database),
        SeerTeamQueryService(
            settings.seer.team,
            headless,
            seer_database.error_message,
            team_resource,
        ),
        EquipmentQueryService(seer_database, seer_images),
        TypeQueryService(
            seer_database,
            partial(
                render_type_matchup,
                render_cache,
                seer_images,
                render_html_template,
            ),
        ),
        BattleEffectQueryService(seer_database, seer_images),
        PetQueryService(
            seer_database,
            seer_images,
            partial(
                render_custom_pet_info,
                render_cache,
                seer_images,
                render_html_template,
            ),
        ),
        PeakQueryService(
            seer_database,
            headless,
            partial(
                render_peak_pool,
                render_cache,
                seer_images,
                render_html_template,
            ),
            partial(
                render_peak_pool_vote,
                seer_images,
                render_html_template,
            ),
            partial(
                render_peak_pet_rank,
                images=seer_images,
                render_html=render_html_template,
            ),
        ),
        MintmarkQueryService(
            seer_database,
            seer_images,
            merge_connected=settings.seer.mintmark.merge_connected,
        ),
        player,
        player_detail_extensions,
        rank_queries,
        rank_admin,
    )
    ai = AiService(
        settings.ai,
        features,
        admin_notices,
        tuple(settings.seer.team_resource.commands),
        HttpAiCompletionClient(http_clients.origin, settings.ai),
        (
            SqliteAiMemoryStore(settings.ai.memory_path)
            if settings.ai.memory and settings.ai.memory_turns > 0
            else None
        ),
    )
    private_extension_runtime = PrivateExtensionRuntime(
        features=features,
        seer=seer,
        headless=headless,
        headless_sessions=headless_sessions,
        data=seer_database,
        images=seer_images,
        render_html=render_html_template,
        error_message=seer_database.error_message,
        player_quotas=player_query_quotas,
        player_requests=player_requests,
        player_details=player_detail_extensions,
        scheduler=scheduler,
        admin_notices=admin_notices,
        release_priority=priority.release,
        settings=settings.operations.private_extensions.settings,
    )
    docker_update = DockerUpdateService(
        settings.operations.docker_update,
        docker_client,
        partial(
            terminate_bot_process,
            signal_parent=True,
            reason="admin requested bot restart",
        ),
        handoff_store=DockerStartupPreflightStore(),
    )
    command_catalog = CommandCatalog()

    def poke_hint_candidates(
        group_id: int | None,
        user_id: int,
        group_role: str | None,
        ignored_plugins: tuple[str, ...],
    ):
        return command_catalog.poke_candidates_for_context(
            CommandContext(
                user_id=user_id,
                group_id=group_id,
                group_role=group_role,
            ),
            features,
            ignored_plugins=ignored_plugins,
        )

    resources = ApplicationResources(
        features=features,
        outbound=outbound,
        delivery=delivery,
        push_message_limiter=push_message_limiter,
        admin_notices=admin_notices,
        activity=activity,
        headless=headless,
        server_status=ServerStatusService(
            headless,
            HttpServerNoticeSource(http_clients.origin),
        ),
        priority=priority,
        subscriptions=subscriptions,
        bilibili=bilibili,
        bilibili_login=bilibili_login,
        messaging=messaging,
        sendpic=sendpic,
        team_audit=team_audit,
        team_resource=team_resource,
        local_rank=local_rank,
        rank_page_refresh=rank_page_refresh,
        seer=seer,
        pet_config=pet_config,
        ai=ai,
        data_sync=data_sync,
        docker_update=docker_update,
        startup_notice=StartupNoticeService(admin_notices),
        commands=command_catalog,
        help_hint=HelpHintService(
            settings.features.help,
            settings.onebot_references,
            poke_hint_candidates,
        ),
        private_extensions=private_extensions,
        private_extension_runtime=private_extension_runtime,
    )
    plugins = build_plugin_registry(
        settings=settings,
        resources=resources,
        scheduler=scheduler,
    )
    command_catalog.load(
        plugins,
        known_features=(
            *(feature.value for feature in Feature),
            *features.command_features,
            *features.schedule_features,
        ),
    )
    matchers = MatcherRegistry(
        CommandCooldownService(settings.messaging.command_cooldown, features),
        settings.bot.matcher_priority,
        before_reply_send=priority.wait,
        prompt_session_manager=prompt_sessions,
        in_flight_requests=InFlightRequestService(
            features,
            settings.messaging.command_cooldown,
        ),
    )
    lifecycle = ApplicationLifecycle.from_plugins(
        driver,
        plugins,
        task_owner=task_owner,
        resource_shutdown_hooks=(
            ("file_logging", file_logging.close),
            ("http_clients", http_clients.close),
            ("databases", databases.close),
        ),
    )
    return Application(
        settings=settings,
        driver=driver,
        asgi=nonebot.get_asgi(),
        scheduler=scheduler,
        file_logging=file_logging,
        http_clients=http_clients,
        databases=databases,
        prompt_sessions=prompt_sessions,
        resources=resources,
        plugins=plugins,
        matchers=matchers,
        lifecycle=lifecycle,
    )
