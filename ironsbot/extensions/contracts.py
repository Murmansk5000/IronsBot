# SPDX-License-Identifier: MIT
"""Narrow public contexts for separately distributed extension packages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.seer.errors import ErrorMessageLookup
    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.player_query_limits import PlayerQueryQuotaService
    from ironsbot.services.seer.player_request_protection import (
        PlayerRequestProtectionService,
    )
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer


@dataclass(frozen=True, slots=True)
class PlayerDetailActionRequest:
    """Validated player target and platform context for an extension action."""

    player_id: int
    actor: Any
    conversation: Any


@dataclass(frozen=True, slots=True)
class PlayerDetailActionRegistration:
    """Public description of one optional player-detail action."""

    action_id: str
    feature: str
    label: str
    aliases: tuple[str, ...]
    command_help_id: str
    query: Any
    action: Any
    work_unit: str = "lineup"


@dataclass(frozen=True, slots=True)
class PlayerLineupSlot:
    """One raw selected pet supplied by an optional lineup extension."""

    pet_id: int
    level: int
    use_flag: int
    skin_id: int = 0


@dataclass(frozen=True, slots=True)
class PlayerLineupPetSnapshot:
    """Published data required to render one resolved lineup slot."""

    pet_id: int
    level: int
    use_flag: int
    name: str
    resource_id: int
    type_id: int
    peak_pool_limit: int | None


class PlayerLineupEntryResolver(Protocol):
    """Resolve private lineup slots without exposing ORM records."""

    def resolve(
        self,
        slots: tuple[PlayerLineupSlot, ...],
    ) -> tuple[PlayerLineupPetSnapshot, ...]: ...


class PlayerLineupExtensionContext(Protocol):
    """Dependencies permitted to the optional player-lineup extension.

    The application may carry a broader private-extension runtime internally,
    but a separately distributed lineup package may depend only on this stable
    contract. It must never import application composition or public plugin
    implementation modules to acquire those dependencies.
    """

    headless: HeadlessService
    lineup_entries: PlayerLineupEntryResolver
    images: SeerImageSource
    render_cache: RenderCache
    render_html: HtmlTemplateRenderer
    error_message: ErrorMessageLookup
    player_quotas: PlayerQueryQuotaService
    player_requests: PlayerRequestProtectionService
    player_id_resolver: PlayerIdResolver

    def settings_for(self, extension_id: str) -> Mapping[str, Any]: ...

    def is_feature_visible_in_help(self, event: object, feature: str) -> bool: ...

    def register_player_detail_action(
        self, registration: PlayerDetailActionRegistration
    ) -> None: ...
