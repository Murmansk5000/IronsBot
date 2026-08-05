# SPDX-License-Identifier: MIT
"""Concrete public context for the optional player-lineup extension."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.player_references import PlayerReferenceLookup
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.errors import ErrorMessageLookup
    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.player_detail_extensions import (
        PlayerDetailExtensionRegistry,
    )
    from ironsbot.services.seer.player_query_limits import PlayerQueryQuotaService
    from ironsbot.services.seer.player_request_protection import (
        PlayerRequestProtectionService,
    )
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer


@dataclass(frozen=True, slots=True)
class PlayerLineupExtensionServices:
    """Dependencies intentionally available to the player-lineup extension."""

    features: FeatureService
    headless: HeadlessService
    data: SeerDataAccess
    images: SeerImageSource
    render_cache: RenderCache
    render_html: HtmlTemplateRenderer
    error_message: ErrorMessageLookup
    player_quotas: PlayerQueryQuotaService
    player_requests: PlayerRequestProtectionService
    player_details: PlayerDetailExtensionRegistry
    player_reference_lookup: PlayerReferenceLookup
    settings: Mapping[str, Any]

    def settings_for(self, extension_id: str) -> Mapping[str, Any]:
        if extension_id != "player_lineup":
            return {}
        return self.settings
