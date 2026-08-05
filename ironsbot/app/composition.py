# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

from ironsbot.app.activity_composition import build_activity_service
from ironsbot.app.application import Application
from ironsbot.app.bilibili_composition import build_onebot_bilibili_monitor
from ironsbot.app.file_logging import FileLogging
from ironsbot.app.lifecycle import TaskOwner
from ironsbot.app.private_extensions import (
    load_private_extension_catalog,
)
from ironsbot.app.rendering_composition import build_seer_rendering_components
from ironsbot.app.resources import ApplicationResources
from ironsbot.config.models.features import build_onebot_feature_service
from ironsbot.core.features import Feature
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.core.promotions import PromotionCatalog
from ironsbot.extensions.player_lineup import PlayerLineupExtensionServices
from ironsbot.integrations.db_registry import DatabaseManager
from ironsbot.integrations.db_sync.runner import DatabaseSync
from ironsbot.integrations.docker.client import DockerClient
from ironsbot.integrations.headless_seer.client import ClientManager
from ironsbot.integrations.headless_seer.rank import fetch_rank_page
from ironsbot.integrations.http.activity_notice import UnityNoticeSource
from ironsbot.integrations.http.ai import HttpAiCompletionClient
from ironsbot.integrations.http.bilibili import (
    fetch_bili_account_name,
    fetch_bili_feed,
    poll_bili_login_qr,
    request_bili_login_qr,
)
from ironsbot.integrations.http.clients import HttpClients
from ironsbot.integrations.http.server_notice import HttpServerNoticeSource
from ironsbot.integrations.onebot.activity import OneBotActivityReminderSender
from ironsbot.integrations.onebot.admin_notice import OneBotAdminNoticeSender
from ironsbot.integrations.onebot.bilibili_rendering import (
    build_dynamic_content_message,
)
from ironsbot.integrations.onebot.bilibili_targets import (
    build_onebot_bili_configured_targets,
)
from ironsbot.integrations.onebot.delivery import OneBotDelivery
from ironsbot.integrations.onebot.group_probe import OneBotGroupProbe
from ironsbot.integrations.onebot.help_hint import OneBotHelpHintService
from ironsbot.integrations.onebot.identity import (
    onebot_actor_ref,
    onebot_conversation_ref,
)
from ironsbot.integrations.onebot.lucky_skin_window import (
    OneBotLuckySkinWindowNotificationSender,
    OneBotLuckySkinWindowSubscriptionOptions,
    build_onebot_lucky_skin_window_accounts,
)
from ironsbot.integrations.onebot.matchers import MatcherFactory, PromptSessionManager
from ironsbot.integrations.onebot.messaging_config import (
    build_onebot_message_schedule_targets,
)
from ironsbot.integrations.onebot.outbound import (
    GroupOutboundRateLimitService,
    install_outbound_rate_limit_hooks,
)
from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
from ironsbot.integrations.onebot.promotions import append_promotions_for_target
from ironsbot.integrations.onebot.router import BotRouter
from ironsbot.integrations.onebot.scheduled_delivery import (
    OneBotScheduledMessageSender,
)
from ironsbot.integrations.onebot.team_audit import (
    OneBotTeamAuditMembershipProbe,
    OneBotTeamAuditPolicy,
)
from ironsbot.integrations.onebot.team_resource import (
    OneBotTeamResourceNoticeSender,
    build_onebot_team_resource_default_mentions,
)
from ironsbot.integrations.process import terminate_bot_process
from ironsbot.integrations.scheduler.facade import SchedulerFacade
from ironsbot.integrations.seer_data.database import SeerDatabase
from ironsbot.integrations.seer_data.new_content_renderer import (
    render_new_content_menu,
)
from ironsbot.integrations.seer_data.peak_pet_rank_renderer import (
    render_peak_pet_rank,
)
from ironsbot.integrations.seer_data.peak_pool_renderer import render_peak_pool
from ironsbot.integrations.seer_data.peak_pool_vote_renderer import (
    render_peak_pool_vote,
)
from ironsbot.integrations.seer_data.pet_info_renderer import render_published_pet_info
from ironsbot.integrations.seer_data.type_matchup_renderer import render_type_matchup
from ironsbot.integrations.sendpic import SendpicBackendProvider
from ironsbot.integrations.storage.ai_memory import SqliteAiMemoryStore
from ironsbot.integrations.storage.bilibili_cookie import FileBiliCookieStore
from ironsbot.integrations.storage.bilibili_history import (
    SqliteBiliDynamicHistoryStore,
)
from ironsbot.integrations.storage.bilibili_preferences import (
    SqliteBiliPushPreferenceStore,
)
from ironsbot.integrations.storage.local_rank import SqliteLocalRankRepository
from ironsbot.integrations.storage.lucky_skin_watch import (
    SqliteLuckySkinWatchPreferenceStore,
)
from ironsbot.integrations.storage.lucky_skin_window import (
    SqliteLuckySkinWindowCache,
)
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
from ironsbot.integrations.storage.team_audit import SqliteTeamAuditReminderStore
from ironsbot.integrations.storage.team_resources import (
    TeamResourceSubscriptionStore,
)
from ironsbot.runtime.cache_paths import CachePaths
from ironsbot.runtime.commands import CommandCatalog, CommandContext
from ironsbot.runtime.in_flight_requests import InFlightRequestService
from ironsbot.runtime.plugins import PluginContributionCatalog
from ironsbot.services.ai.service import AiService
from ironsbot.services.bilibili.accounts import BiliAccountNames
from ironsbot.services.bilibili.login import BilibiliLoginService
from ironsbot.services.bilibili.service import BilibiliService
from ironsbot.services.bilibili.targets import BiliTargetService
from ironsbot.services.messaging.admin_notice import AdminNoticeService
from ironsbot.services.messaging.command_cooldown import CommandCooldownService
from ironsbot.services.messaging.sendpic import SendpicService
from ironsbot.services.operations.data_sync import DataSyncService
from ironsbot.services.operations.docker_preflight import DockerStartupPreflightStore
from ironsbot.services.operations.docker_update import DockerUpdateService
from ironsbot.services.operations.headless import HeadlessService
from ironsbot.services.operations.headless_activity import HeadlessOperationTracker
from ironsbot.services.operations.headless_session import HeadlessSessionFactory
from ironsbot.services.operations.scheduled_restart import ScheduledRestartService
from ironsbot.services.operations.server_status import ServerStatusService
from ironsbot.services.operations.startup import StartupNoticeService
from ironsbot.services.pet_config import PetConfigQueryService
from ironsbot.services.seer.autocard import AutocardService
from ironsbot.services.seer.battle_effect import BattleEffectQueryService
from ironsbot.services.seer.countermark_stat_rank import CountermarkStatRankService
from ironsbot.services.seer.data_queries import SeerDataQueryService
from ironsbot.services.seer.equipment import EquipmentQueryService
from ironsbot.services.seer.local_rank import LocalRankService
from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowService
from ironsbot.services.seer.mintmark import MintmarkQueryService
from ironsbot.services.seer.new_content import NewContentService
from ironsbot.services.seer.peak import PeakQueryService
from ironsbot.services.seer.pet_query import PetQueryService
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
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
from ironsbot.services.seer.resources import SeerQueryResources
from ironsbot.services.seer.team import SeerTeamQueryService
from ironsbot.services.seer.type_query import TypeQueryService
from ironsbot.services.team.audit import TeamAuditService
from ironsbot.services.team.resource import TeamResourceService

if TYPE_CHECKING:
    from ironsbot.config.models.settings import Settings

SEERAPI_DB_NAME = "seerapi"


def build_application(settings: Settings) -> Application:  # noqa: PLR0915
    from ironsbot.services.messaging.service import MessagingService

    driver = nonebot.get_driver()
    driver.register_adapter(OneBotV11Adapter)
    scheduler = SchedulerFacade()
    file_logging = FileLogging.create(settings.bot.logging, settings.paths)
    http_clients = HttpClients()
    databases = DatabaseManager()
    cache_paths = CachePaths(settings.paths.cache_root)
    database_sync = DatabaseSync(databases, cache_paths=cache_paths)
    task_owner = TaskOwner()
    for name, source in settings.operations.data_sync.sources.items():
        database_sync.register(name, source)
    data_sync = DataSyncService(settings.operations.data_sync, database_sync)
    seer_database = SeerDatabase(
        databases,
        merge_connected_mintmarks=settings.seer.mintmark.merge_connected,
    )
    prompt_sessions = PromptSessionManager()
    promotions = PromotionCatalog(settings.promotions)
    features = build_onebot_feature_service(
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
    subscriptions = PushUnsubscribeStore(settings.paths.qq_state)
    player_bindings = SqlitePlayerBindingStore(settings.paths.qq_state)
    bot_router = BotRouter(
        settings.messaging.bot_routing,
        settings.onebot_references,
    )
    delivery = OneBotDelivery(
        outbound,
        settings.messaging.push_unsubscribe,
        bot_router,
        subscriptions,
    )
    push_message_limiter = partial(
        append_promotions_for_target,
        features,
        promotions,
    )
    admin_notices = AdminNoticeService(features, OneBotAdminNoticeSender(delivery))
    install_outbound_rate_limit_hooks(outbound)

    activity = build_activity_service(
        settings.activity,
        settings.paths.runtime_state,
        features,
        OneBotActivityReminderSender(delivery, push_message_limiter),
        databases,
        subscriptions,
        UnityNoticeSource(
            http_clients.origin,
            settings.activity.notice_timeout_seconds,
        ),
    )
    headless_operations = HeadlessOperationTracker()
    player_accounts = settings.player_accounts

    def resolve_configured_player_reference(
        reference: str,
        conversation: ConversationRef,
    ) -> int | None:
        return player_accounts.resolve_player_id(
            reference,
            conversation=conversation,
        )

    headless_accounts = settings.headless_accounts
    headless_worker_count = len(headless_accounts)
    headless = HeadlessService(
        [
            ClientManager(
                task_owner.create,
                operations=headless_operations,
            )
            for _ in range(headless_worker_count)
        ],
        settings.operations.headless,
        settings.operations.headless_notice,
        admin_notices,
        accounts=headless_accounts,
        request_interval_seconds=(
            settings.seer.player.request_protection.base_request_interval_seconds
            if settings.seer.player.request_protection.enabled
            else 0.0
        ),
        spawn=task_owner.create,
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
    lucky_skin_window = LuckySkinWindowService(
        settings.seer.lucky_skin_window,
        build_onebot_lucky_skin_window_accounts(
            settings.seer.lucky_skin_window,
            settings.onebot_references,
            player_accounts,
        ),
        features,
        headless_sessions,
        seer_database,
        player_bindings,
        SqliteLuckySkinWatchPreferenceStore(settings.paths.qq_state),
        SqliteLuckySkinWindowCache(settings.paths.runtime_state),
        OneBotLuckySkinWindowNotificationSender(delivery, subscriptions),
    )
    bili_data_dir = settings.bilibili.storage.data_dir
    bili_cookie_store = FileBiliCookieStore(bili_data_dir / "bili_cookie_cache.txt")
    bilibili = BilibiliService(
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
        OneBotScheduledMessageSender(delivery, push_message_limiter),
        build_onebot_message_schedule_targets(
            settings.messaging,
            settings.onebot_references,
        ),
        (
            bilibili.targets.subscription_options,
            OneBotLuckySkinWindowSubscriptionOptions(
                lucky_skin_window,
                subscriptions,
            ).subscription_options,
        ),
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
        TeamResourceSubscriptionStore(settings.paths.qq_state),
        headless,
        features,
        OneBotTeamResourceNoticeSender(delivery),
        build_onebot_team_resource_default_mentions(
            settings.seer.team_resource,
            settings.onebot_references,
        ),
    )
    team_audit = TeamAuditService(
        settings.messaging.team_audit_welcome,
        SqliteTeamAuditReminderStore(settings.paths.runtime_state),
        OneBotTeamAuditPolicy(features),
        OneBotOutboundMessenger(bot_router, outbound),
        OneBotTeamAuditMembershipProbe(bot_router, OneBotGroupProbe()),
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
    seer_images, render_cache, render_coordinator = build_seer_rendering_components(
        http_clients,
        cache_paths,
        settings.seer.render,
        seer_database,
    )
    player_query_quotas = PlayerQueryQuotaService(
        settings.seer.player.query_limits,
        player_bindings,
        features,
        SqlitePlayerQueryLimitStore(settings.paths.qq_state),
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
    local_rank_repository = SqliteLocalRankRepository(
        settings.seer.local_rank.path,
        settings.seer.local_rank.max_players,
    )
    local_rank = LocalRankService(
        local_rank_repository,
        settings.seer.local_rank,
        settings.seer.player,
        rank,
        player_requests,
        rank.exclusion_policy,
    )
    local_rank.remove_excluded_samples()
    rank_display = RankDisplayService(
        settings.seer.rank,
        {
            ConversationRef(Platform.ONEBOT, "group", str(group_id)): limit
            for reference, limit in settings.seer.rank.display_limits.items()
            for group_id in (
                settings.onebot_references.resolve_group(
                    reference,
                    location=f"seer.rank.display_limits.{reference}",
                ),
            )
        },
        SqliteRankDisplayStore(settings.paths.qq_state),
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
        profile_cache=local_rank_repository,
    )
    player_id_resolver = PlayerIdResolver(
        resolve_configured_player_reference,
        player.default_player_id,
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
            player_timeout_seconds=(settings.seer.player.detail_timeout_seconds),
        ),
        player_query_quotas,
        player_requests,
    )
    rank_admin = RankAdminService(
        RankAdminPolicy(
            rank_limit=settings.seer.rank.limit,
            batch_limit=settings.seer.local_rank.batch_limit,
            refresh_limit=settings.seer.local_rank.refresh_limit,
            refresh_max_age_hours=(settings.seer.local_rank.refresh_max_age_hours),
            page_cache_ttl_seconds=(settings.seer.rank.page_cache_ttl_seconds),
            display_limit=rank_display.limit_for_conversation,
        ),
        rank,
        local_rank,
        rank_page_refresh,
        headless,
        player_requests,
    )
    autocard = AutocardService(seer_database)
    seer = SeerQueryResources(
        SeerDataQueryService(
            seer_database,
            seer_images,
            settings.seer.season,
            NewContentService(seer_database),
        ),
        CountermarkStatRankService(seer_database),
        autocard,
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
                render_coordinator.render,
            ),
        ),
        BattleEffectQueryService(seer_database, seer_images),
        PetQueryService(
            seer_database,
            seer_images,
            partial(
                render_published_pet_info,
                render_cache,
                seer_database,
                seer_images,
                render_coordinator.render,
            ),
        ),
        PeakQueryService(
            seer_database,
            headless,
            partial(
                render_peak_pool,
                render_cache,
                seer_images,
                render_coordinator.render,
            ),
            partial(
                render_peak_pool_vote,
                render_cache,
                seer_images,
                render_coordinator.render,
            ),
            partial(
                render_peak_pet_rank,
                render_cache,
                seer_images,
                render_coordinator.render,
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
        partial(
            render_new_content_menu,
            render_cache,
            seer_database,
            seer_images,
            autocard,
            render_coordinator.render,
        ),
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
    bilibili_monitor = build_onebot_bilibili_monitor(
        service=bilibili,
        login=bilibili_login,
        delivery=delivery,
        subscriptions=subscriptions,
        admin_notices=admin_notices,
        message_limiter=push_message_limiter,
        ai_service=ai,
        config=settings.bilibili,
    )
    extension_contexts = {
        "player_lineup": PlayerLineupExtensionServices(
            features=features,
            headless=headless,
            data=seer_database,
            images=seer_images,
            render_cache=render_cache,
            render_html=render_coordinator.render,
            error_message=seer_database.error_message,
            player_quotas=player_query_quotas,
            player_requests=player_requests,
            player_details=player_detail_extensions,
            player_reference_lookup=resolve_configured_player_reference,
            settings=settings.operations.private_extensions.settings.get(
                "player_lineup", {}
            ),
        )
    }
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
    scheduled_restart = ScheduledRestartService(
        restart_times=(
            tuple(settings.operations.restart.parsed_restart_times)
            if settings.operations.restart.enabled
            else ()
        ),
        grace_seconds=settings.operations.restart.grace_seconds,
        restart_process=partial(
            terminate_bot_process,
            signal_parent=settings.operations.restart.signal_parent,
            reason="scheduled bot restart",
        ),
    )
    command_catalog = CommandCatalog()
    contribution_catalog = PluginContributionCatalog()

    def poke_hint_candidates(
        group_id: int | None,
        user_id: int,
        group_role: str | None,
        ignored_plugins: tuple[str, ...],
    ):
        actor = onebot_actor_ref(user_id)
        return command_catalog.poke_candidates_for_context(
            CommandContext(
                actor=actor,
                conversation=onebot_conversation_ref(user_id, group_id=group_id),
                group_role=group_role,
            ),
            features,
            ignored_plugins=ignored_plugins,
        )

    resources = ApplicationResources(
        features=features,
        promotions=promotions,
        outbound=outbound,
        delivery=delivery,
        push_message_limiter=push_message_limiter,
        admin_notices=admin_notices,
        activity=activity,
        headless=headless,
        server_status=ServerStatusService(
            headless,
            HttpServerNoticeSource(http_clients.origin),
            dedicated_sessions=headless_sessions,
        ),
        subscriptions=subscriptions,
        bilibili=bilibili,
        bilibili_login=bilibili_login,
        bilibili_monitor=bilibili_monitor,
        bilibili_content_renderer=build_dynamic_content_message,
        lucky_skin_window=lucky_skin_window,
        messaging=messaging,
        sendpic=sendpic,
        team_audit=team_audit,
        team_resource=team_resource,
        local_rank=local_rank,
        rank_page_refresh=rank_page_refresh,
        player_id_resolver=player_id_resolver,
        seer=seer,
        pet_config=pet_config,
        ai=ai,
        data_sync=data_sync,
        docker_update=docker_update,
        startup_notice=StartupNoticeService(admin_notices),
        scheduled_restart=scheduled_restart,
        commands=command_catalog,
        contribution_catalog=contribution_catalog,
        help_hint=OneBotHelpHintService(
            settings.features.help,
            settings.onebot_references,
            poke_hint_candidates,
        ),
        private_extensions=private_extensions,
    )
    matcher_factory = MatcherFactory(
        CommandCooldownService(settings.messaging.command_cooldown, features),
        settings.bot.matcher_priority,
        prompt_session_manager=prompt_sessions,
        in_flight_requests=InFlightRequestService(
            features,
            settings.messaging.command_cooldown,
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
        contributions=(),
        matcher_factory=matcher_factory,
        extension_contexts=extension_contexts,
        task_owner=task_owner,
        known_features=(
            *(feature.value for feature in Feature),
            *settings.messaging.command_feature_keys,
            *settings.messaging.schedule_feature_keys,
        ),
        required_plugin_features=frozenset(
            feature
            for feature in Feature
            if feature.value in features.configured_feature_keys
        ),
        resource_shutdown_hooks=(
            ("file_logging", file_logging.close),
            ("http_clients", http_clients.close),
            ("databases", databases.close),
        ),
    )
