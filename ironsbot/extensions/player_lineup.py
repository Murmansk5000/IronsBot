# SPDX-License-Identifier: MIT
"""Concrete public context for the optional player-lineup extension."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ironsbot.extensions.contracts import PlayerLineupImageAssets
from ironsbot.integrations.seer_data.pet_image_assets import load_pet_image_assets
from ironsbot.services.seer.player_detail_extensions import PlayerDetailExtensionAction
from ironsbot.services.seer.rendering.cache_key import render_document_cache_key

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from ironsbot.extensions.contracts import (
        PlayerDetailActionRegistration,
        PlayerLineupEntryResolver,
        PlayerLineupRenderPort,
    )
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.seer.errors import ErrorMessageLookup
    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.player_detail_extensions import (
        PlayerDetailExtensionRegistry,
    )
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.player_query_limits import PlayerQueryQuotaService
    from ironsbot.services.seer.player_request_protection import (
        PlayerRequestProtectionService,
    )
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer


@dataclass(frozen=True, slots=True)
class PlayerLineupRenderServices:
    """Concrete adapter for the public private-lineup rendering port."""

    images: SeerImageSource
    cache: RenderCache
    render: HtmlTemplateRenderer

    async def image_assets(
        self,
        *,
        resource_ids: tuple[int, ...],
        type_ids: tuple[int, ...],
    ) -> PlayerLineupImageAssets:
        assets = await load_pet_image_assets(
            self.images,
            resource_ids=resource_ids,
            type_ids=type_ids,
        )
        return PlayerLineupImageAssets(
            pet_heads=assets.pet_heads,
            type_icons=assets.type_icons,
        )

    def cache_key(self, document: object, *, renderer_fingerprint: str) -> str:
        return render_document_cache_key(
            document,
            renderer_fingerprint=renderer_fingerprint,
        )

    def cached_image(self, category: str, key: str) -> bytes | None:
        return self.cache.get(category, key)

    def cache_image(self, category: str, key: str, image: bytes) -> None:
        self.cache.put(category, key, image)

    async def render_html(
        self,
        *,
        template_path: Path,
        template_name: str,
        templates: Mapping[str, object],
        max_width: int,
        allow_refit: bool,
    ) -> bytes:
        return await self.render(
            template_path=template_path,
            template_name=template_name,
            templates=templates,
            max_width=max_width,
            allow_refit=allow_refit,
        )


@dataclass(frozen=True, slots=True)
class PlayerLineupExtensionServices:
    """Dependencies intentionally available to the player-lineup extension."""

    headless: HeadlessService
    lineup_entries: PlayerLineupEntryResolver
    lineup_render: PlayerLineupRenderPort
    error_message: ErrorMessageLookup
    player_quotas: PlayerQueryQuotaService
    player_requests: PlayerRequestProtectionService
    feature_visible: Callable[[object, str], bool]
    _player_details: PlayerDetailExtensionRegistry
    player_id_resolver: PlayerIdResolver
    settings: Mapping[str, Any]

    def settings_for(self, extension_id: str) -> Mapping[str, Any]:
        if extension_id != "player_lineup":
            return {}
        return self.settings

    def is_feature_visible_in_help(self, event: object, feature: str) -> bool:
        """Expose feature visibility without leaking platform policy internals."""

        return self.feature_visible(event, feature)

    def register_player_detail_action(
        self, registration: PlayerDetailActionRegistration
    ) -> None:
        """Register an optional action through the public extension boundary."""

        self._player_details.register(
            PlayerDetailExtensionAction(
                id=registration.action_id,
                feature=registration.feature,
                label=registration.label,
                aliases=registration.aliases,
                command_help_id=registration.command_help_id,
                query=registration.query,
                action=registration.action,
                work_unit=registration.work_unit,
            )
        )
