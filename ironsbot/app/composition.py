# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

import nonebot
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

from ironsbot.app.activity_composition import build_activity_service
from ironsbot.app.ai_health import check_configured_ai_api
from ironsbot.app.application import Application
from ironsbot.app.bilibili_composition import (
    build_onebot_bilibili_components,
    build_onebot_bilibili_monitor,
)
from ironsbot.app.clock_check import check_configured_clock
from ironsbot.app.common_composition import build_common_components
from ironsbot.app.file_logging import FileLogging
from ironsbot.app.lifecycle import TaskOwner
from ironsbot.app.messaging_composition import build_messaging_components
from ironsbot.app.operations_composition import build_operations_components
from ironsbot.app.private_extensions import (
    load_private_extension_catalog,
)
from ironsbot.app.resources import ApplicationResources
from ironsbot.app.seer_composition import build_seer_components
from ironsbot.core.command_catalog import CommandCatalog, CommandContext
from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import PluginContributionCatalog
from ironsbot.extensions.player_lineup import (
    PlayerLineupCacheServices,
    PlayerLineupExtensionServices,
    PlayerLineupQueryServices,
)
from ironsbot.integrations.db_registry import DatabaseManager
from ironsbot.integrations.http.activity_notice import UnityNoticeSource
from ironsbot.integrations.http.ai import HttpAiCompletionClient
from ironsbot.integrations.http.clients import HttpClients
from ironsbot.integrations.onebot.bilibili_rendering import (
    build_dynamic_content_message,
)
from ironsbot.integrations.onebot.feature_policy import event_is_feature_visible_in_help
from ironsbot.integrations.onebot.help_hint import OneBotHelpHintService
from ironsbot.integrations.onebot.identity import (
    onebot_actor_ref,
    onebot_conversation_ref,
)
from ironsbot.integrations.onebot.matchers import MatcherFactory
from ironsbot.integrations.scheduler.facade import SchedulerFacade
from ironsbot.integrations.storage.ai_memory import SqliteAiMemoryStore
from ironsbot.integrations.storage.player_bindings import (
    SqlitePlayerBindingStore,
)
from ironsbot.runtime.cache_paths import CachePaths
from ironsbot.runtime.in_flight_requests import InFlightRequestService
from ironsbot.services.activity.outbound_sender import ActivityReminderOutboundSender
from ironsbot.services.ai.service import AiService
from ironsbot.services.messaging.command_cooldown import CommandCooldownService

if TYPE_CHECKING:
    from ironsbot.config.models.settings import Settings


def build_application(settings: Settings) -> Application:  # noqa: PLR0915
    driver = nonebot.get_driver()
    driver.register_adapter(OneBotV11Adapter)
    scheduler = SchedulerFacade()
    file_logging = FileLogging.create(settings.bot.logging, settings.paths)
    http_clients = HttpClients()
    databases = DatabaseManager()
    cache_paths = CachePaths(settings.paths.cache_root)
    task_owner = TaskOwner()
    common = build_common_components(settings, task_owner)
    prompt_sessions = common.prompt_sessions
    features = common.features
    promotions = common.promotions
    outbound = common.outbound
    subscriptions = common.subscriptions
    bot_router = common.bot_router
    proactive_delivery = common.proactive_delivery
    admin_notices = common.admin_notices
    player_bindings = SqlitePlayerBindingStore(settings.paths.qq_state)
    operations = build_operations_components(
        settings,
        databases,
        cache_paths,
        task_owner,
        admin_notices,
        http_clients,
    )
    data_sync = operations.data_sync
    seer_database = operations.seer_database
    headless = operations.headless
    headless_sessions = operations.headless_sessions

    activity = build_activity_service(
        settings.activity,
        settings.paths.runtime_state,
        features,
        ActivityReminderOutboundSender(proactive_delivery),
        databases,
        subscriptions,
        UnityNoticeSource(
            http_clients.origin,
            settings.activity.notice_timeout_seconds,
        ),
    )
    seer_components = build_seer_components(
        settings,
        http_clients,
        cache_paths,
        task_owner,
        features,
        proactive_delivery,
        subscriptions,
        seer_database,
        headless,
        headless_sessions,
        player_bindings,
    )
    lucky_skin_window = seer_components.lucky_skin_window
    bilibili_components = build_onebot_bilibili_components(
        settings,
        http_clients,
        features,
        subscriptions,
        task_owner,
    )
    bilibili = bilibili_components.service
    bilibili_login = bilibili_components.login
    messaging_components = build_messaging_components(
        settings,
        http_clients,
        features,
        proactive_delivery,
        subscriptions,
        bot_router,
        outbound,
        bilibili.targets,
        lucky_skin_window,
    )
    messaging = messaging_components.messaging
    sendpic = messaging_components.sendpic
    team_audit = messaging_components.team_audit
    team_resource = seer_components.team_resource
    player_query_quotas = seer_components.player_query_quotas
    player_requests = seer_components.player_requests
    pet_config = seer_components.pet_config
    local_rank = seer_components.local_rank
    rank_page_refresh = seer_components.rank_page_refresh
    player_id_resolver = seer_components.player_id_resolver
    player_detail_extensions = seer_components.player_detail_extensions
    seer = seer_components.seer
    private_extensions = load_private_extension_catalog(
        settings.operations.private_extensions
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
        subscriptions=subscriptions,
        admin_notices=admin_notices,
        bot_router=bot_router,
        proactive_delivery=proactive_delivery,
        ai_service=ai,
        config=settings.bilibili,
    )
    def feature_visible_for_extension(event: object, feature: str) -> bool:
        return (
            isinstance(event, Event)
            and event_is_feature_visible_in_help(features, event, feature)
        )

    extension_contexts = {
        "player_lineup": PlayerLineupExtensionServices(
            lineup_render_session=seer_components.lineup_render_session,
            lineup_query=PlayerLineupQueryServices(
                headless=headless,
                error_message=seer_database.error_message,
                quotas=player_query_quotas,
                requests=player_requests,
            ),
            lineup_cache=PlayerLineupCacheServices(),
            feature_visible=feature_visible_for_extension,
            _player_details=player_detail_extensions,
            player_id_resolver=player_id_resolver,
            settings=settings.operations.private_extensions.settings.get(
                "player_lineup", {}
            ),
        )
    }
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
        admin_notices=admin_notices,
        activity=activity,
        headless=headless,
        server_status=operations.server_status,
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
        ai_startup_check=partial(
            check_configured_ai_api,
            settings.ai,
            operations.startup_notice,
        ),
        clock_startup_check=partial(
            check_configured_clock,
            settings.operations.clock_check,
            operations.startup_notice,
        ),
        data_sync=data_sync,
        docker_update=operations.docker_update,
        startup_notice=operations.startup_notice,
        scheduled_restart=operations.scheduled_restart,
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
