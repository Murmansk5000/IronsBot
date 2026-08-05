# SPDX-License-Identifier: MIT
"""Narrow public contexts for separately distributed extension packages."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

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


class PlayerLineupExtensionContext(Protocol):
    """Dependencies permitted to the optional player-lineup extension.

    The application may carry a broader private-extension runtime internally,
    but a separately distributed lineup package may depend only on this stable
    contract. It must never import application composition or public plugin
    implementation modules to acquire those dependencies.
    """

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

    def settings_for(self, extension_id: str) -> Mapping[str, Any]: ...
