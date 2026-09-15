# SPDX-License-Identifier: MIT
"""Compose Seer query services, data repositories, and render dependencies."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from ironsbot.app.rendering_composition import build_seer_rendering_components
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.extensions.contracts import PlayerLineupRenderSession
from ironsbot.extensions.player_lineup import PlayerLineupRenderServices
from ironsbot.integrations.headless_seer.rank import fetch_rank_page
from ironsbot.integrations.http.weekly_preview_images import (
    CachedWeeklyPreviewImageSource,
)
from ironsbot.integrations.onebot.lucky_skin_window import (
    build_onebot_lucky_skin_window_accounts,
)
from ironsbot.integrations.onebot.team_resource import (
    build_onebot_team_resource_default_mentions,
)
from ironsbot.integrations.seer_data.autocard_repository import (
    PublishedAutocardRepository,
)
from ironsbot.integrations.seer_data.autocard_sanctuary_repository import (
    PublishedAutocardSanctuaryRepository,
)
from ironsbot.integrations.seer_data.data_query_repository import (
    PublishedDataQueryRepository,
)
from ironsbot.integrations.seer_data.lucky_skin_window_renderer import (
    render_lucky_skin_window,
)
from ironsbot.integrations.seer_data.new_content_renderer import (
    render_new_content_menu,
)
from ironsbot.integrations.seer_data.new_content_repository import (
    PublishedNewContentRepository,
)
from ironsbot.integrations.seer_data.peak_pet_rank_renderer import (
    render_peak_pet_rank,
)
from ironsbot.integrations.seer_data.peak_pool_renderer import render_peak_pool
from ironsbot.integrations.seer_data.peak_pool_vote_renderer import (
    render_peak_pool_vote,
)
from ironsbot.integrations.seer_data.peak_repository import PublishedPeakRepository
from ironsbot.integrations.seer_data.pet_info_renderer import render_published_pet_info
from ironsbot.integrations.seer_data.player_lineup_entries import (
    PublishedPlayerLineupEntryResolver,
)
from ironsbot.integrations.seer_data.type_matchup_renderer import render_type_matchup
from ironsbot.integrations.seer_data.type_matchup_repository import (
    PublishedTypeMatchupRepository,
)
from ironsbot.integrations.storage.local_rank import SqliteLocalRankRepository
from ironsbot.integrations.storage.lucky_skin_watch import (
    SqliteLuckySkinWatchPreferenceStore,
)
from ironsbot.integrations.storage.lucky_skin_window import (
    SqliteLuckySkinWindowCache,
)
from ironsbot.integrations.storage.pet_config_images import FilePetConfigImageStore
from ironsbot.integrations.storage.player_query_limits import (
    SqlitePlayerQueryLimitStore,
)
from ironsbot.integrations.storage.rank_display import SqliteRankDisplayStore
from ironsbot.integrations.storage.rank_page_cache import SqliteRankPageCache
from ironsbot.integrations.storage.team_resources import (
    TeamResourceSubscriptionStore,
)
from ironsbot.services.pet_config import PetConfigQueryService
from ironsbot.services.seer.autocard import AutocardService
from ironsbot.services.seer.autocard_media import AutocardMediaService
from ironsbot.services.seer.autocard_sanctuary import AutocardSanctuaryService
from ironsbot.services.seer.battle_effect import BattleEffectQueryService
from ironsbot.services.seer.countermark_stat_rank import CountermarkStatRankService
from ironsbot.services.seer.data_queries import SeerDataQueryService
from ironsbot.services.seer.equipment import EquipmentQueryService
from ironsbot.services.seer.external_references import SeerInfoReferences
from ironsbot.services.seer.local_rank import LocalRankService
from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowService
from ironsbot.services.seer.lucky_skin_window_delivery import (
    LuckySkinWindowOutboundSender,
)
from ironsbot.services.seer.mintmark import MintmarkQueryService
from ironsbot.services.seer.new_content import NewContentService
from ironsbot.services.seer.new_content_details import NewContentDetailService
from ironsbot.services.seer.peak import PeakQueryService, PeakRenderSession
from ironsbot.services.seer.pet_query import PetQueryService
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_detail_service import PlayerDetailService
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.player_query_limits import PlayerQueryQuotaService
from ironsbot.services.seer.player_request_protection import (
    PlayerRequestProtectionService,
)
from ironsbot.services.seer.player_service import PlayerService
from ironsbot.services.seer.rank import RankService
from ironsbot.services.seer.rank_admin import RankAdminPolicy, RankAdminService
from ironsbot.services.seer.rank_display import RankDisplayService
from ironsbot.services.seer.rank_page_refresh import RankPageRefreshService
from ironsbot.services.seer.rank_queries import RankQueryPolicy, RankQueryService
from ironsbot.services.seer.resources import SeerQueryResources
from ironsbot.services.seer.team import (
    SeerTeamQueryService,
    player_team_detail_action,
)
from ironsbot.services.seer.type_query import TypeQueryService, TypeRenderSession
from ironsbot.services.team.resource import TeamResourceService
from ironsbot.services.team.resource_delivery import TeamResourceOutboundSender

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.app.lifecycle import TaskOwner
    from ironsbot.config.models.settings import Settings
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.extensions.contracts import PlayerLineupRenderSessionFactory
    from ironsbot.integrations.http.clients import HttpClients
    from ironsbot.integrations.seer_data.database import SeerDatabase
    from ironsbot.integrations.storage.player_bindings import SqlitePlayerBindingStore
    from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
    from ironsbot.runtime.cache_paths import CachePaths
    from ironsbot.services.messaging.proactive_delivery import ProactiveMessageDelivery
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.operations.headless_session import HeadlessSessionFactory
    from ironsbot.services.seer.lucky_skin_window import (
        LuckySkinWindowOffer,
        LuckySkinWindowResult,
    )
    from ironsbot.services.seer.new_content import (
        NewContentCategory,
        NewContentSnapshot,
    )


@dataclass(frozen=True, slots=True)
class SeerComponents:
    """Seer-facing services and their reusable rendering dependencies."""

    seer: SeerQueryResources
    lucky_skin_window: LuckySkinWindowService
    team_resource: TeamResourceService
    local_rank: LocalRankService
    rank_page_refresh: RankPageRefreshService
    pet_config: PetConfigQueryService
    player_id_resolver: PlayerIdResolver
    player_query_quotas: PlayerQueryQuotaService
    player_requests: PlayerRequestProtectionService
    player_detail_extensions: PlayerDetailExtensionRegistry
    lineup_render_session: PlayerLineupRenderSessionFactory


def build_seer_components(  # noqa: PLR0913, PLR0915 - explicit composition boundary
    settings: Settings,
    http_clients: HttpClients,
    cache_paths: CachePaths,
    task_owner: TaskOwner,
    features: FeatureService,
    proactive_delivery: ProactiveMessageDelivery,
    subscriptions: PushUnsubscribeStore,
    seer_database: SeerDatabase,
    headless: HeadlessService,
    headless_sessions: HeadlessSessionFactory,
    player_bindings: SqlitePlayerBindingStore,
) -> SeerComponents:
    """Build all Seer query and render services in dependency order."""
    player_accounts = settings.player_accounts

    def resolve_configured_player_reference(
        reference: str,
        conversation: ConversationRef,
    ) -> int | None:
        return player_accounts.resolve_player_id(
            reference,
            conversation=conversation,
        )

    def resolve_privileged_player_reference(
        reference: str,
        conversation: ConversationRef,
    ) -> int | None:
        return player_accounts.resolve_player_id(
            reference,
            conversation=conversation,
            include_private=True,
        )

    team_resource = TeamResourceService(
        settings.seer.team_resource,
        TeamResourceSubscriptionStore(settings.paths.qq_state),
        headless,
        features,
        TeamResourceOutboundSender(proactive_delivery),
        build_onebot_team_resource_default_mentions(
            settings.seer.team_resource,
            settings.onebot_references,
        ),
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
    images, render_coordinator, render_sessions = (
        build_seer_rendering_components(
            http_clients,
            cache_paths,
            settings.seer.render,
            seer_database,
            spawn=task_owner.create,
        )
    )

    async def render_pet(pet_id: int) -> bytes:
        with render_sessions.open() as inputs:
            return await render_published_pet_info(
                inputs.cache,
                inputs.data,
                inputs.images,
                render_coordinator.render,
                pet_id,
            )

    @contextmanager
    def type_render_session() -> Iterator[TypeRenderSession]:
        with render_sessions.open() as inputs:
            yield TypeRenderSession(
                PublishedTypeMatchupRepository(inputs.data),
                partial(
                    render_type_matchup,
                    inputs.images,
                    render_coordinator.render,
                ),
                inputs.cache,
            )

    @contextmanager
    def peak_render_session() -> Iterator[PeakRenderSession]:
        with render_sessions.open() as inputs:
            yield PeakRenderSession(
                PublishedPeakRepository(inputs.data),
                partial(
                    render_peak_pool,
                    inputs.cache,
                    inputs.images,
                    render_coordinator.render,
                ),
                partial(
                    render_peak_pool_vote,
                    inputs.cache,
                    inputs.images,
                    render_coordinator.render,
                ),
                partial(
                    render_peak_pet_rank,
                    inputs.cache,
                    inputs.images,
                    render_coordinator.render,
                ),
                NewContentService(PublishedNewContentRepository(inputs.data)),
            )

    async def render_window(
        result: LuckySkinWindowResult, offers: tuple[LuckySkinWindowOffer, ...]
    ) -> bytes:
        with render_sessions.open() as inputs:
            return await render_lucky_skin_window(
                inputs.cache,
                inputs.data,
                inputs.images,
                render_coordinator.render,
                result,
                offers,
            )

    @contextmanager
    def lineup_render_session() -> Iterator[PlayerLineupRenderSession]:
        with render_sessions.open() as inputs:
            yield PlayerLineupRenderSession(
                PublishedPlayerLineupEntryResolver(inputs.data),
                PlayerLineupRenderServices(
                    images=inputs.images,
                    cache=inputs.cache,
                    render=render_coordinator.render,
                ),
            )

    @contextmanager
    def content_selection_scope(snapshot: NewContentSnapshot) -> Iterator[None]:
        with seer_database.read_snapshot() as bound:
            NewContentService(PublishedNewContentRepository(bound)).require_snapshot(
                snapshot
            )
            bound.require_current()
            yield
            bound.require_current()

    async def render_content_menu(  # noqa: PLR0913
        snapshot: NewContentSnapshot,
        display_categories: tuple[NewContentCategory, ...],
        focused_category: NewContentCategory | None,
        menu_title: str,
        expanded_categories: frozenset[NewContentCategory],
        auto_expand_max_items: int,
    ) -> bytes:
        with render_sessions.open() as inputs:
            NewContentService(
                PublishedNewContentRepository(inputs.data)
            ).require_snapshot(snapshot)
            return await render_new_content_menu(
                inputs.cache,
                inputs.data,
                inputs.images,
                AutocardService(PublishedAutocardRepository(inputs.data)),
                render_coordinator.render,
                snapshot,
                display_categories,
                focused_category,
                menu_title,
                expanded_categories,
                auto_expand_max_items,
            )

    weekly_preview_images = CachedWeeklyPreviewImageSource(
        http_clients.origin,
        cache_paths.http_dir() / "weekly_preview",
        spawn=task_owner.create,
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
        LuckySkinWindowOutboundSender(proactive_delivery, subscriptions),
        player_accounts=player_accounts,
        renderer=render_window,
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
        privileged_reference_lookup=resolve_privileged_player_reference,
        is_privileged_actor=features.is_actor_superuser,
    )
    player_detail_extensions = PlayerDetailExtensionRegistry()
    team_query = SeerTeamQueryService(
        settings.seer.team,
        headless,
        seer_database.error_message,
        team_resource,
    )
    player_detail_extensions.register(player_team_detail_action(team_query))
    rank_queries = RankQueryService(
        rank,
        local_rank,
        rank_display,
        headless,
        RankQueryPolicy(
            player_error=player.format_error,
            player_timeout_seconds=settings.seer.player.detail_timeout_seconds,
        ),
        player_query_quotas,
        player_requests,
    )
    rank_admin = RankAdminService(
        RankAdminPolicy(
            rank_limit=settings.seer.rank.limit,
            batch_limit=settings.seer.local_rank.batch_limit,
            refresh_limit=settings.seer.local_rank.refresh_limit,
            refresh_max_age_hours=settings.seer.local_rank.refresh_max_age_hours,
            page_cache_ttl_seconds=settings.seer.rank.page_cache_ttl_seconds,
            display_limit=rank_display.limit_for_conversation,
        ),
        rank,
        local_rank,
        rank_page_refresh,
        headless,
        player_requests,
    )
    autocard = AutocardService(PublishedAutocardRepository(seer_database))
    autocard_media = AutocardMediaService(images)
    autocard_sanctuary = AutocardSanctuaryService(
        PublishedAutocardSanctuaryRepository(seer_database)
    )
    equipment = EquipmentQueryService(seer_database, images)
    pet = PetQueryService(seer_database, images, render_pet)
    mintmark = MintmarkQueryService(
        seer_database,
        images,
        merge_connected=settings.seer.mintmark.merge_connected,
    )
    external_references = SeerInfoReferences(settings.seer.external_references)
    return SeerComponents(
        seer=SeerQueryResources(
            SeerDataQueryService(
                PublishedDataQueryRepository(seer_database),
                weekly_preview_images,
                settings.seer.season,
                NewContentService(PublishedNewContentRepository(seer_database)),
            ),
            CountermarkStatRankService(seer_database),
            autocard,
            autocard_media,
            autocard_sanctuary,
            team_query,
            equipment,
            TypeQueryService(
                type_render_session,
            ),
            BattleEffectQueryService(seer_database, images),
            pet,
            PeakQueryService(
                PublishedPeakRepository(seer_database),
                headless,
                peak_render_session,
            ),
            mintmark,
            player,
            player_detail_extensions,
            rank_queries,
            rank_admin,
            render_content_menu,
            NewContentDetailService(
                pet, mintmark, equipment, autocard, content_selection_scope
            ),
            external_references,
        ),
        lucky_skin_window=lucky_skin_window,
        team_resource=team_resource,
        local_rank=local_rank,
        rank_page_refresh=rank_page_refresh,
        pet_config=pet_config,
        player_id_resolver=player_id_resolver,
        player_query_quotas=player_query_quotas,
        player_requests=player_requests,
        player_detail_extensions=player_detail_extensions,
        lineup_render_session=lineup_render_session,
    )
