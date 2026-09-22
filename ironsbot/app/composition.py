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
from ironsbot.app.official_address_composition import build_official_addresses
from ironsbot.app.operations_composition import build_operations_components
from ironsbot.app.private_extensions import (
    load_private_extension_catalog,
)
from ironsbot.app.resources import ApplicationResources
from ironsbot.app.seer_composition import build_seer_components
from ironsbot.core.command_catalog import CommandCatalog, CommandContext
from ironsbot.core.features import Feature
from ironsbot.core.platform import ActorRef, Platform
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
from ironsbot.integrations.onebot.identity import (
    onebot_actor_ref,
    onebot_conversation_ref,
)
from ironsbot.integrations.onebot.ingress_policy import OneBotIngressPolicy
from ironsbot.integrations.onebot.matchers import MatcherFactory
from ironsbot.integrations.onebot.poke_reply import OneBotPokeReplyService
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
from ironsbot.services.identity_link_store import (
    CrossPlatformIdentityLink,
    OfficialIdentity,
)
from ironsbot.services.identity_linking import IdentityLinkingService, OfficialAccount
from ironsbot.services.identity_observation import (
    IdentityObservationAccount,
    SilentIdentityObservationService,
)
from ironsbot.services.identity_principals import IdentityPrincipalService
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.messaging.command_cooldown import CommandCooldownService
from ironsbot.services.messaging.command_recommendations import (
    CommandRecommendationService,
)
from ironsbot.services.official_union_identity import OfficialUnionIdentityService
from ironsbot.services.portable_query_sessions import PortableQuerySessions

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.config.models.settings import Settings
    from ironsbot.core.plugin_install import NamedLifecycleHook
    from ironsbot.integrations.qq_official.runtime import QQOfficialRuntime
    from ironsbot.services.bilibili.targets import BiliTargetService
    from ironsbot.services.identity_link_store import (
        CrossPlatformGroupLink,
    )
    from ironsbot.services.identity_principals import (
        ActorPrincipalMerge,
        ConversationPrincipalMerge,
    )
    from ironsbot.services.official_addresses import OfficialAddressService
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


def _register_configured_identity_principals(
    settings: Settings,
    principals: IdentityPrincipalService,
) -> tuple[ConversationPrincipalMerge, ...]:
    accounts = settings.bot.qq_official.enabled_accounts
    merges: list[ConversationPrincipalMerge] = []
    for alias, target in settings.identities.users.items():
        principals.register_configured_actor(
            alias=alias,
            onebot_qq_id=None if target.qq is None else str(target.qq),
            official_endpoints=tuple(
                (account.app_id, openid)
                for account_alias, openid in target.official.items()
                if (account := accounts.get(account_alias)) is not None
            ),
        )
        if target.qq is not None:
            for account_alias, openid in target.official.items():
                if (account := accounts.get(account_alias)) is not None:
                    merges.extend(
                        principals.register_private_link(
                            CrossPlatformIdentityLink(
                                str(target.qq),
                                OfficialIdentity(account.app_id, "user", openid),
                                0,
                            )
                        )
                    )
    for alias, target in settings.identities.groups.items():
        endpoints: list[tuple[str, str]] = []
        for account_alias, openid in target.official.items():
            account = accounts.get(account_alias)
            if account is not None:
                endpoints.append((account.app_id, openid))
        merges.extend(
            principals.register_configured_group(
                alias=alias,
                onebot_group_id=None if target.qq is None else str(target.qq),
                official_endpoints=endpoints,
            )
        )
    return tuple(merges)


def _apply_conversation_merges(
    merges: tuple[ConversationPrincipalMerge, ...],
    merge: Callable[[ConversationPrincipalMerge], None],
) -> None:
    for item in merges:
        merge(item)


async def _load_identity_links(  # noqa: PLR0913
    store: SqliteIdentityLinkStore,
    principals: IdentityPrincipalService,
    observer: SilentIdentityObservationService | None,
    bili_targets: BiliTargetService,
    on_principal_merge: Callable[[ActorPrincipalMerge], None],
    on_conversation_merge: Callable[[ConversationPrincipalMerge], None],
    qq_official: QQOfficialRuntime | None,
    addresses: OfficialAddressService | None = None,
) -> None:
    for observation in await store.all_union_identities():
        official = observation.official
        merges = principals.observe_union_identity(
            actor=ActorRef(
                Platform.QQ_OFFICIAL,
                official.openid,
                kind=official.kind if official.scope_id else "user",
                scope_id=official.scope_id or None,
                account_id=official.app_id,
            ),
            evidence=observation.union_identity,
        )
        for merge in merges:
            on_principal_merge(merge)
    for link in await store.all_group_links():
        for merge in principals.register_group_link(link):
            on_conversation_merge(merge)
        selected_for_outbound = qq_official is None or qq_official.register_group_link(
            link
        )
        if observer is not None:
            observer.register_group_link(link)
        if selected_for_outbound:
            bili_targets.register_group_link(
                official_app_id=link.official_app_id,
                official_group_openid=link.official_group_openid,
                onebot_group_id=link.onebot_group_id,
            )
    links = await store.all_links()
    for link in links:
        for merge in principals.register_identity_link(link):
            on_principal_merge(merge)
    if addresses is not None:
        await addresses.load(links)


def build_application(settings: Settings) -> Application:  # noqa: PLR0915
    driver = nonebot.get_driver()
    driver.register_adapter(OneBotV11Adapter)
    scheduler = SchedulerFacade()
    file_logging = FileLogging.create(settings.bot.logging, settings.paths)
    http_clients = HttpClients()
    databases = DatabaseManager()
    cache_paths = CachePaths(settings.paths.cache_root)
    task_owner = TaskOwner()
    identity_principals = IdentityPrincipalService()
    configured_conversation_merges = _register_configured_identity_principals(
        settings,
        identity_principals,
    )
    common = build_common_components(
        settings,
        task_owner,
        identity_principals,
        http_client=http_clients.origin,
        cache_root=settings.paths.cache_root,
    )
    prompt_sessions = common.prompt_sessions
    features = common.features
    promotions = common.promotions
    outbound = common.outbound
    subscriptions = common.subscriptions
    _apply_conversation_merges(
        configured_conversation_merges,
        lambda merge: subscriptions.merge_principals(merge.source, merge.target),
    )
    bot_router = common.bot_router
    proactive_delivery = common.proactive_delivery
    admin_notices = common.admin_notices
    player_bindings = SqlitePlayerBindingStore(
        settings.paths.qq_state,
        principal_for=identity_principals.actor_principal,
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
    query_sessions = PortableQuerySessions()
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
        identity_principals,
        admin_notices,
        query_sessions,
        common.private_routes,
    )
    _apply_conversation_merges(
        configured_conversation_merges,
        lambda merge: seer_components.rank_display_store.merge_principals(
            merge.source,
            merge.target,
        ),
    )
    _apply_conversation_merges(
        configured_conversation_merges,
        lambda merge: seer_components.team_resource_store.merge_conversation_principals(
            merge.source,
            merge.target,
        ),
    )
    lucky_skin_window = seer_components.lucky_skin_window
    bilibili_components = build_bilibili_components(
        settings,
        http_clients,
        features,
        subscriptions,
        task_owner,
        identity_principals,
        common.private_routes,
    )
    bilibili = bilibili_components.service
    bilibili_login = bilibili_components.login
    _apply_conversation_merges(
        configured_conversation_merges,
        lambda merge: bilibili_components.preferences.merge_principals(
            merge.source,
            merge.target,
        ),
    )
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
        identity_principals,
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
    ai_memory = (
        SqliteAiMemoryStore(
            settings.ai.memory_path,
            principal_for=identity_principals.actor_principal,
        )
        if settings.ai.memory and settings.ai.memory_turns > 0
        else None
    )
    ai = AiService(
        settings.ai,
        features,
        admin_notices,
        tuple(settings.seer.team_resource.commands),
        identity_principals,
        HttpAiCompletionClient(http_clients.origin, settings.ai),
        ai_memory,
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

    def merge_actor_principal(merge: ActorPrincipalMerge) -> None:
        player_bindings.merge_principals(merge.source, merge.target)
        seer_components.player_query_limit_store.merge_principals(
            merge.source,
            merge.target,
        )
        seer_components.lucky_skin_preference_store.merge_principals(
            merge.source,
            merge.target,
        )
        seer_components.team_resource_store.merge_actor_principals(
            merge.source,
            merge.target,
        )
        if ai_memory is not None:
            ai_memory.merge_principals(merge.source, merge.target)

    def merge_conversation_principal(merge: ConversationPrincipalMerge) -> None:
        subscriptions.merge_principals(merge.source, merge.target)
        bilibili_components.preferences.merge_principals(merge.source, merge.target)
        seer_components.rank_display_store.merge_principals(
            merge.source,
            merge.target,
        )
        seer_components.team_resource_store.merge_conversation_principals(
            merge.source,
            merge.target,
        )

    addresses = build_official_addresses(
        settings,
        identity_principals,
        bilibili_components.service.targets,
        merge_conversation_principal,
    )

    def register_identity_link(link: CrossPlatformIdentityLink) -> None:
        for merge in identity_principals.register_identity_link(link):
            merge_actor_principal(merge)
        addresses.accept_link(link)

    def unregister_identity_link(link: CrossPlatformIdentityLink) -> None:
        identity_principals.unregister_identity_link(link)
        addresses.refresh()

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
    union_identity = (
        OfficialUnionIdentityService(
            identity_store,
            common.admin_notices,
            identity_principals,
            merge_actor_principal,
            register_identity_link,
            addresses=addresses,
        )
        if common.qq_official is not None
        else None
    )
    identity_observer = _build_identity_observer(
        settings,
        identity_store,
        identity_principals,
        bilibili.targets,
        merge_actor_principal,
        merge_conversation_principal,
        common.qq_official,
        addresses=addresses,
    )
    onebot_ingress = OneBotIngressPolicy(
        messages_enabled=(
            settings.outbound_platform_selection.onebot_message_handling_enabled
        ),
        identity_observer=identity_observer,
    )

    def poke_reply_candidates(
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

    from ironsbot.services.portable_menu_access import (
        explicit_command_resolver,
        menu_access_resolver,
    )

    query_sessions.access_resolver = menu_access_resolver(command_catalog, features)
    query_sessions.explicit_command = explicit_command_resolver(
        command_catalog, features
    )
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
        poke_reply=OneBotPokeReplyService(
            settings.features.help,
            settings.onebot_references,
            poke_reply_candidates,
        ),
        addressed_input_hints=AddressedInputHintService(
            window_seconds=settings.features.help.hint_window_seconds,
            max_per_window=settings.features.help.hint_max_per_window,
            recommendations=CommandRecommendationService(
                command_catalog, features, settings.features.help
            ),
        ),
        identity_links=identity_links,
        identity_linking=identity_linking,
        identity_principals=identity_principals,
        identity_observer=identity_observer,
        union_identity=union_identity,
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
    query_sessions.interactions.request_service = matcher_factory.in_flight_requests
    query_sessions.interactions.cooldown = matcher_factory.cooldown
    resource_startup_hooks: list[NamedLifecycleHook] = [
        (
            "identity_links",
            partial(
                _load_identity_links,
                identity_store,
                identity_principals,
                identity_observer,
                bilibili.targets,
                merge_actor_principal,
                merge_conversation_principal,
                common.qq_official,
                addresses,
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
        resource_startup_hooks.append(
            (
                "bilibili_official_recovery",
                partial(bilibili_monitor.check_on_connect, "qq_official"),
            )
        )
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


def _build_identity_observer(  # noqa: PLR0913 - explicit composition dependencies
    settings: Settings,
    store: SqliteIdentityLinkStore,
    principals: IdentityPrincipalService,
    bili_targets: BiliTargetService,
    on_principal_merge: Callable[[ActorPrincipalMerge], None],
    on_conversation_merge: Callable[[ConversationPrincipalMerge], None],
    qq_official: QQOfficialRuntime | None,
    addresses: OfficialAddressService | None = None,
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
        for merge in principals.register_official_link(
            onebot_qq_id=qq_id,
            official=official,
        ):
            on_principal_merge(merge)
        if addresses is not None:
            addresses.refresh()

    def register_group_link(link: CrossPlatformGroupLink) -> None:
        for merge in principals.register_group_link(link):
            on_conversation_merge(merge)
        selected_for_outbound = qq_official is None or qq_official.register_group_link(
            link
        )
        if selected_for_outbound:
            bili_targets.register_group_link(
                official_app_id=link.official_app_id,
                official_group_openid=link.official_group_openid,
                onebot_group_id=link.onebot_group_id,
            )

    return SilentIdentityObservationService(
        store,
        accounts,
        on_link=register_link,
        on_group_link=register_group_link,
    )
