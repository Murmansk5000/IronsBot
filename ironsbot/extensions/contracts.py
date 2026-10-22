# SPDX-License-Identifier: MIT
"""Narrow public contexts for separately distributed extension packages."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from ironsbot.core.command_catalog import CommandAccess
from ironsbot.core.player_detail_actions import (
    PlayerDetailActionRequest as PlayerDetailActionRequest,  # noqa: PLC0414, TC001 - public extension export
)
from ironsbot.services.seer.render_cache import (
    RenderCacheEntry as RenderCacheEntry,  # noqa: PLC0414, TC001 - public extension export
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Mapping
    from pathlib import Path

    from ironsbot.core.command_catalog import CommandContext
    from ironsbot.core.platform import ActorRef, ConversationRef
    from ironsbot.core.semantic_requests import ActionDefinition
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.query_result import QueryReply


@dataclass(frozen=True, slots=True)
class PlayerDetailActionRegistration:
    """Public description of one optional player-detail action."""

    action_id: str
    feature: str
    label: str
    aliases: tuple[str, ...]
    command_help_id: str
    query: Callable[[PlayerDetailActionRequest], Awaitable[QueryReply]]
    action: ActionDefinition
    work_unit: str = "lineup"
    access: tuple[CommandAccess, ...] = (CommandAccess(),)
    show_in_player_menu: bool = True
    numeric_target_only: bool = False
    offer_binding: bool = True


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
    master_pool_cost: int
    complete: bool
    skin_name: str | None = None


class PlayerLineupEntryResolver(Protocol):
    """Resolve private lineup slots without exposing ORM records."""

    def resolve(
        self,
        slots: tuple[PlayerLineupSlot, ...],
    ) -> tuple[PlayerLineupPetSnapshot, ...]: ...


@dataclass(frozen=True, slots=True)
class PlayerLineupTraitSnapshot:
    effect_id: int
    args: tuple[int, ...]
    name: str
    description: str
    star_level: int | None


@dataclass(frozen=True, slots=True)
class PlayerLineupDetailCatalog:
    skill_names: tuple[tuple[int, str], ...] = ()
    mintmark_names: tuple[tuple[int, str], ...] = ()
    traits: tuple[PlayerLineupTraitSnapshot, ...] = ()


class PlayerLineupDetailResolver(Protocol):
    def resolve(
        self,
        *,
        skill_ids: tuple[int, ...],
        mintmark_ids: tuple[int, ...],
        effect_ids: tuple[int, ...],
    ) -> PlayerLineupDetailCatalog: ...


@dataclass(frozen=True, slots=True)
class PlayerLineupImageAssets:
    """Image facts prepared for a private lineup render document."""

    pet_heads: tuple[tuple[int, str], ...]
    type_icons: tuple[tuple[int, str], ...]
    complete: bool = True

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

    def request_cache_key(
        self,
        category: str,
        request: object,
        *,
        renderer_fingerprint: str,
    ) -> str: ...

    def cache_entry(self, category: str, key: str) -> RenderCacheEntry: ...

    async def render_html(
        self,
        *,
        template_path: Path,
        template_name: str,
        templates: Mapping[str, object],
        max_width: int,
        allow_refit: bool,
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class PlayerLineupRenderSession:
    """Entry and image capabilities bound to one published data generation."""

    entries: PlayerLineupEntryResolver
    render: PlayerLineupRenderPort
    details: PlayerLineupDetailResolver | None = None


PlayerLineupRenderSessionFactory = Callable[
    [], AbstractContextManager[PlayerLineupRenderSession]
]


@dataclass(frozen=True, slots=True)
class PlayerLineupQueryResult:
    """Safe public result of one private lineup data request."""

    leading_text: str = ""
    payload: bytes | None = None
    error: str = ""
    record_success: Callable[[], None] | None = None
    fetched_at: float | None = None
    cache_fallback_allowed: bool = False

    @property
    def succeeded(self) -> bool:
        return self.payload is not None and not self.error


class PlayerLineupPacketClient(Protocol):
    """Minimal packet capability needed by a private lineup parser."""

    async def request(
        self,
        command_id: int,
        player_id: int,
        *body: int,
        timeout_seconds: float,
    ) -> bytes: ...


class PlayerLineupPacketFetcher(Protocol):
    async def __call__(
        self,
        client: PlayerLineupPacketClient,
        player_id: int,
        *,
        timeout_seconds: float,
    ) -> bytes: ...


class PlayerLineupQueryPort(Protocol):
    """Run a private lineup packet request through public player safeguards."""

    async def query(  # noqa: PLR0913 - guarded packet request and settlement policy
        self,
        *,
        player_id: int,
        actor: ActorRef,
        conversation: ConversationRef,
        timeout_seconds: float,
        fetch_packet: PlayerLineupPacketFetcher,
        defer_quota: bool = False,
        label: str = "阵容",
    ) -> PlayerLineupQueryResult: ...


@dataclass(frozen=True, slots=True)
class PlayerLineupCachedReply:
    """Persistent private-lineup reply data owned by the public cache port."""

    leading_text: str = ""
    text: str = ""
    image: bytes | None = None
    image_error: str = ""
    fetched_at: float | None = None


class PlayerLineupCachePort(Protocol):
    """Read and write completed lineup replies without exposing SQLite."""

    def get(self, player_id: int) -> PlayerLineupCachedReply | None: ...

    def put(self, player_id: int, reply: PlayerLineupCachedReply) -> None: ...


class PlayerLineupCacheFactory(Protocol):
    """Open a public cache port at the extension's declared cache path."""

    def open(self, path: str) -> PlayerLineupCachePort: ...


class PlayerLineupExtensionContext(Protocol):
    """Dependencies permitted to the optional player-lineup extension.

    The application may carry a broader private-extension runtime internally,
    but a separately distributed lineup package may depend only on this stable
    contract. It must never import application composition or public plugin
    implementation modules to acquire those dependencies.
    """

    @property
    def lineup_render_session(self) -> PlayerLineupRenderSessionFactory: ...

    @property
    def lineup_query(self) -> PlayerLineupQueryPort: ...

    @property
    def lineup_cache(self) -> PlayerLineupCacheFactory: ...

    @property
    def player_id_resolver(self) -> PlayerIdResolver: ...

    def settings_for(self, extension_id: str) -> Mapping[str, Any]: ...

    def is_feature_visible_in_help(
        self, context: CommandContext, feature: str
    ) -> bool: ...

    def register_player_detail_action(
        self, registration: PlayerDetailActionRegistration
    ) -> None: ...
