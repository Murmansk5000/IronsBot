# SPDX-License-Identifier: MIT
"""Narrow public contexts for separately distributed extension packages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.seer.errors import ErrorMessageLookup
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.player_query_limits import PlayerQueryQuotaService
    from ironsbot.services.seer.player_request_protection import (
        PlayerRequestProtectionService,
    )


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


@dataclass(frozen=True, slots=True)
class PlayerLineupImageAssets:
    """Image facts prepared for a private lineup render document."""

    pet_heads: tuple[tuple[int, str], ...]
    type_icons: tuple[tuple[int, str], ...]

    @property
    def pet_head_by_resource_id(self) -> dict[int, str]:
        return dict(self.pet_heads)

    @property
    def type_icon_by_id(self) -> dict[int, str]:
        return dict(self.type_icons)


class PlayerLineupRenderPort(Protocol):
    """Rendering capabilities deliberately available to the lineup extension."""

    async def image_assets(
        self,
        *,
        resource_ids: tuple[int, ...],
        type_ids: tuple[int, ...],
    ) -> PlayerLineupImageAssets: ...

    def cache_key(self, document: object, *, renderer_fingerprint: str) -> str: ...

    def cached_image(self, category: str, key: str) -> bytes | None: ...

    def cache_image(self, category: str, key: str, image: bytes) -> None: ...

    async def render_html(
        self,
        *,
        template_path: Path,
        template_name: str,
        templates: Mapping[str, object],
        max_width: int,
        allow_refit: bool,
    ) -> bytes: ...


class PlayerLineupExtensionContext(Protocol):
    """Dependencies permitted to the optional player-lineup extension.

    The application may carry a broader private-extension runtime internally,
    but a separately distributed lineup package may depend only on this stable
    contract. It must never import application composition or public plugin
    implementation modules to acquire those dependencies.
    """

    headless: HeadlessService
    lineup_entries: PlayerLineupEntryResolver
    lineup_render: PlayerLineupRenderPort
    error_message: ErrorMessageLookup
    player_quotas: PlayerQueryQuotaService
    player_requests: PlayerRequestProtectionService
    player_id_resolver: PlayerIdResolver

    def settings_for(self, extension_id: str) -> Mapping[str, Any]: ...

    def is_feature_visible_in_help(self, event: object, feature: str) -> bool: ...

    def register_player_detail_action(
        self, registration: PlayerDetailActionRegistration
    ) -> None: ...
