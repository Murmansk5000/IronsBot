# SPDX-License-Identifier: MIT
"""Concrete public context for the optional player-lineup extension."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ironsbot.services.seer.player_detail_extensions import PlayerDetailExtensionAction

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from ironsbot.extensions.contracts import (
        PlayerDetailActionRegistration,
        PlayerLineupEntryResolver,
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
class PlayerLineupExtensionServices:
    """Dependencies intentionally available to the player-lineup extension."""

    headless: HeadlessService
    lineup_entries: PlayerLineupEntryResolver
    images: SeerImageSource
    render_cache: RenderCache
    render_html: HtmlTemplateRenderer
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
