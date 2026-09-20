# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

import nonebot
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

from ironsbot.app.activity_composition import build_activity_service
from ironsbot.app.ai_health import check_configured_ai_api
from ironsbot.app.application import Application
from ironsbot.app.bilibili_composition import (
    build_bilibili_components,
    build_bilibili_monitor,
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
from ironsbot.integrations.onebot.feature_policy import event_is_feature_visible_in_help
from ironsbot.integrations.onebot.help_hint import OneBotHelpHintService
from ironsbot.integrations.onebot.identity import (
    onebot_actor_ref,
    onebot_conversation_ref,
)
from ironsbot.integrations.onebot.ingress_policy import OneBotIngressPolicy
from ironsbot.integrations.onebot.matchers import MatcherFactory
from ironsbot.integrations.scheduler.facade import SchedulerFacade
from ironsbot.integrations.storage.ai_memory import SqliteAiMemoryStore
from ironsbot.integrations.storage.identity_links import SqliteIdentityLinkStore
from ironsbot.integrations.storage.player_bindings import (
    SqlitePlayerBindingStore,
)
from ironsbot.runtime.cache_paths import CachePaths
from ironsbot.runtime.in_flight_requests import InFlightRequestService
from ironsbot.services.about import AboutService
from ironsbot.services.activity.outbound_sender import ActivityReminderOutboundSender
from ironsbot.services.ai.actions import AiIntentActionExecutor
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.ai.service import AiService
from ironsbot.services.identity_link_commands import IdentityLinkCommands
from ironsbot.services.identity_linking import IdentityLinkingService, OfficialAccount
from ironsbot.services.identity_observation import (
    IdentityObservationAccount,
    SilentIdentityObservationService,
)
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.messaging.command_cooldown import CommandCooldownService
from ironsbot.services.portable_query_sessions import PortableQuerySessions

if TYPE_CHECKING:
    from ironsbot.config.models.settings import Settings
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.plugin_install import NamedLifecycleHook
    from ironsbot.integrations.qq_official.runtime import QQOfficialRuntime
    from ironsbot.services.bilibili.targets import BiliTargetService
    from ironsbot.services.identity_link_store import (
        CrossPlatformGroupLink,
        CrossPlatformIdentityLink,
        OfficialIdentity,
    )
    from ironsbot.services.operations.data_sync import DataSyncService
    from ironsbot.services.operations.startup import StartupNoticeService


async def _start_data_sync_resource(
    service: DataSyncService,
    startup_notice: StartupNoticeService,
    scheduler: SchedulerFacade,
) -> None:
    startup_notice.add(
        "startup_data_sync",
        "startup data sync notice",
        await service.startup(scheduler),
    )


async def _load_identity_links(  # noqa: PLR0913
    store: SqliteIdentityLinkStore,
    features: FeatureService,
    observer: SilentIdentityObservationService | None,
    bili_targets: BiliTargetService,
    player_bindings: SqlitePlayerBindingStore,
    qq_official: QQOfficialRuntime | None,
) -> None:
    for link in await store.all_group_links():
        features.register_group_link(
            official_app_id=link.official_app_id,
            official_group_openid=link.official_group_openid,
            onebot_group_id=link.onebot_group_id,
        )
        if observer is not None:
            observer.register_group_link(link)
        bili_targets.register_group_link(
            official_app_id=link.official_app_id,
            official_group_openid=link.official_group_openid,
            onebot_group_id=link.onebot_group_id,
        )
        if qq_official is not None:
            qq_official.register_group_link(link)
    for link in await store.all_links():
        player_bindings.reconcile_identity_link(link)
        features.register_identity_link(
            official_app_id=link.official.app_id,
            official_openid=link.official.openid,
            onebot_qq_id=link.onebot_qq_id,
        )


def build_application(settings: Settings) -> Application:  # noqa: PLR0915
    driver = nonebot.get_driver()
    driver.register_adapter(OneBotV11Adapter)
    scheduler = SchedulerFacade()
    file_logging = FileLogging.create(settings.bot.logging, settings.paths)
    http_clients = HttpClients()
    databases = DatabaseManager()
    cache_paths = CachePaths(settings.paths.cache_root)
    task_owner = TaskOwner()
    common = build_common_components(
        settings,
        task_owner,
        http_client=http_clients.origin,
        cache_root=settings.paths.cache_root,
    )
    prompt_sessions = common.prompt_sessions
    features = common.features
    promotions = common.promotions
    outbound = common.outbound
    subscriptions = common.subscriptions
    bot_router = common.bot_router
    proactive_delivery = common.proactive_delivery
    admin_notices = common.admin_notices
    player_bindings = SqlitePlayerBindingStore(
        settings.paths.qq_state,
        canonicalize_actor=features.canonical_actor,
    )
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
    bilibili_components = build_bilibili_components(
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
    ai_intent_actions = AiIntentActionExecutor(ai, promotions, team_resource)
    bilibili_monitor = build_bilibili_monitor(
        service=bilibili,
        login=bilibili_login,
        subscriptions=subscriptions,
        admin_notices=admin_notices,
        proactive_delivery=proactive_delivery,
        ai_service=ai,
        config=settings.bilibili,
    )

    def feature_visible_for_extension(event: object, feature: str) -> bool:
        return isinstance(event, Event) and event_is_feature_visible_in_help(
            features, event, feature
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
    ai_input_routing = AiInputRoutingService(features, command_catalog)
    identity_store = SqliteIdentityLinkStore(settings.paths.qq_state)

    def register_identity_link(link: CrossPlatformIdentityLink) -> None:
        player_bindings.reconcile_identity_link(link)
        features.register_identity_link(
            official_app_id=link.official.app_id,
            official_openid=link.official.openid,
            onebot_qq_id=link.onebot_qq_id,
        )

    def unregister_identity_link(link: CrossPlatformIdentityLink) -> None:
        features.unregister_identity_link(
            official_app_id=link.official.app_id,
            official_openid=link.official.openid,
        )

    identity_linking = IdentityLinkingService(
        identity_store,
        {
            alias: OfficialAccount(alias, account.app_id)
            for alias, account in settings.bot.qq_official.enabled_accounts.items()
        },
        on_link=register_identity_link,
        on_unlink=unregister_identity_link,
    )
    identity_links = IdentityLinkCommands(identity_linking)
    identity_observer = _build_identity_observer(
        settings,
        identity_store,
        features,
        bilibili.targets,
        common.qq_official,
    )
    onebot_ingress = OneBotIngressPolicy(
        messages_enabled=(
            settings.outbound_platform_selection.onebot_message_handling_enabled
        ),
        identity_observer=identity_observer,
    )

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

    query_sessions = PortableQuerySessions()
    resources = ApplicationResources(
        about=AboutService.from_version_file(Path("__version__")),
        query_sessions=query_sessions,
        features=features,
        promotions=promotions,
        admin_notices=admin_notices,
        activity=activity,
        headless=headless,
        server_status=operations.server_status,
        subscriptions=subscriptions,
        outbound_messenger=common.outbound_messenger,
        qq_official=common.qq_official,
        bilibili=bilibili,
        bilibili_login=bilibili_login,
        bilibili_monitor=bilibili_monitor,
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
        ai_intent_actions=ai_intent_actions,
        ai_input_routing=ai_input_routing,
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
        addressed_input_hints=AddressedInputHintService(
            window_seconds=settings.features.help.hint_window_seconds,
            max_per_window=settings.features.help.hint_max_per_window,
        ),
        identity_links=identity_links,
        identity_linking=identity_linking,
        identity_observer=identity_observer,
        onebot_ingress=onebot_ingress,
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
    resource_startup_hooks: list[NamedLifecycleHook] = [
        (
            "identity_links",
            partial(
                _load_identity_links,
                identity_store,
                features,
                identity_observer,
                bilibili.targets,
                player_bindings,
                common.qq_official,
            ),
        ),
        (
            "data_sync",
            partial(
                _start_data_sync_resource,
                service=data_sync,
                startup_notice=operations.startup_notice,
                scheduler=scheduler,
            ),
        ),
    ]
    resource_shutdown_hooks = [
        ("file_logging", file_logging.close),
        ("http_clients", http_clients.close),
        ("databases", databases.close),
    ]
    if common.qq_official is not None:
        resource_startup_hooks.append(("qq_official", common.qq_official.start))
        resource_shutdown_hooks.append(("qq_official", common.qq_official.stop))

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
        onebot_message_handling_enabled=(
            settings.outbound_platform_selection.onebot_message_handling_enabled
        ),
        resource_startup_hooks=tuple(resource_startup_hooks),
        resource_shutdown_hooks=tuple(resource_shutdown_hooks),
    )


def _build_identity_observer(
    settings: Settings,
    store: SqliteIdentityLinkStore,
    features: FeatureService,
    bili_targets: BiliTargetService,
    qq_official: QQOfficialRuntime | None,
) -> SilentIdentityObservationService | None:
    if not settings.bot.onebot.identity_verification:
        return None
    accounts: dict[str, IdentityObservationAccount] = {}
    candidate_groups = frozenset(
        target.qq
        for target in settings.identities.groups.values()
        if target.qq is not None
    )
    for alias, account in settings.bot.qq_official.enabled_accounts.items():
        groups = {
            target.official[alias]: target.qq
            for target in settings.identities.groups.values()
            if target.qq is not None and alias in target.official
        }
        accounts[account.app_id] = IdentityObservationAccount(
            app_id=account.app_id,
            trusted_onebot_sender_id=(settings.bot.onebot.trusted_official_bots[alias]),
            groups=dict(groups),
            candidate_onebot_group_ids=candidate_groups,
        )

    def register_link(qq_id: str, official: OfficialIdentity) -> None:
        features.register_identity_link(
            official_app_id=official.app_id,
            official_openid=official.openid,
            onebot_qq_id=qq_id,
        )

    def register_group_link(link: CrossPlatformGroupLink) -> None:
        features.register_group_link(
            official_app_id=link.official_app_id,
            official_group_openid=link.official_group_openid,
            onebot_group_id=link.onebot_group_id,
        )
        bili_targets.register_group_link(
            official_app_id=link.official_app_id,
            official_group_openid=link.official_group_openid,
            onebot_group_id=link.onebot_group_id,
        )
        if qq_official is not None:
            qq_official.register_group_link(link)

    return SilentIdentityObservationService(
        store,
        accounts,
        on_link=register_link,
        on_group_link=register_group_link,
    )
