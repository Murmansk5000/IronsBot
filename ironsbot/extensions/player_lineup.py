# SPDX-License-Identifier: MIT
"""Concrete public context for the optional player-lineup extension."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ironsbot.core.time import ObservationTime
from ironsbot.extensions.contracts import (
    PlayerLineupCachedReply,
    PlayerLineupImageAssets,
    PlayerLineupPacketFetcher,
    PlayerLineupQueryResult,
)
from ironsbot.integrations.seer_data.pet_image_assets import load_pet_image_assets
from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration
from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.services.seer.errors import format_player_query_error
from ironsbot.services.seer.player_detail_extensions import PlayerDetailExtensionAction
from ironsbot.services.seer.player_formatting_common import (
    format_player_data_time,
    format_player_identity,
)
from ironsbot.services.seer.player_query_limits import PlayerQueryQuotaExceededError
from ironsbot.services.seer.player_request_protection import (
    PlayerRequestBusyError,
    PlayerRequestPausedError,
    PlayerRequestReconnectError,
    player_request_protection_message,
)
from ironsbot.services.seer.rendering.cache_key import render_request_cache_key

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from ironsbot.core.platform import ActorRef, ConversationRef
    from ironsbot.extensions.contracts import (
        PlayerDetailActionRegistration,
        PlayerLineupCacheFactory,
        PlayerLineupEntryResolver,
        PlayerLineupQueryPort,
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

    def request_cache_key(
        self,
        category: str,
        request: object,
        *,
        renderer_fingerprint: str,
    ) -> str:
        return render_request_cache_key(
            category,
            request,
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


_LINEUP_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS player_lineup_cache (
    player_id INTEGER PRIMARY KEY,
    leading_text TEXT NOT NULL,
    text TEXT NOT NULL,
    image BLOB,
    image_error TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""
_LINEUP_CACHE_MIGRATIONS = (SqliteMigration(1, (_LINEUP_CACHE_SCHEMA,)),)


@dataclass(frozen=True, slots=True)
class _SqlitePlayerLineupCache:
    database: SqliteDatabase

    def get(self, player_id: int) -> PlayerLineupCachedReply | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT leading_text, text, image, image_error
                FROM player_lineup_cache
                WHERE player_id = ?
                """,
                (player_id,),
            ).fetchone()
        if row is None:
            return None
        return PlayerLineupCachedReply(
            leading_text=str(row[0]),
            text=str(row[1]),
            image=None if row[2] is None else bytes(row[2]),
            image_error=str(row[3]),
        )

    def put(self, player_id: int, reply: PlayerLineupCachedReply) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO player_lineup_cache(
                    player_id, leading_text, text, image, image_error, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(player_id) DO UPDATE SET
                    leading_text = excluded.leading_text,
                    text = excluded.text,
                    image = excluded.image,
                    image_error = excluded.image_error,
                    updated_at = excluded.updated_at
                """,
                (
                    player_id,
                    reply.leading_text,
                    reply.text,
                    reply.image,
                    reply.image_error,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )


@dataclass(frozen=True, slots=True)
class PlayerLineupCacheServices:
    """Public SQLite factory for the optional lineup extension's reply cache."""

    def open(self, path: str) -> _SqlitePlayerLineupCache:
        return _SqlitePlayerLineupCache(
            SqliteDatabase(path, migrations=_LINEUP_CACHE_MIGRATIONS)
        )


@dataclass(frozen=True, slots=True)
class _HeadlessLineupPacketClient:
    """Adapt the public headless client to the packet capability extensions need."""

    game: Any

    async def request(
        self,
        command_id: int,
        player_id: int,
        *,
        timeout_seconds: float,
    ) -> bytes:
        _head, payload = await self.game.send_and_wait(
            command_id,
            player_id,
            timeout=timeout_seconds,
        )
        return bytes(payload)


@dataclass(frozen=True, slots=True)
class PlayerLineupQueryServices:
    """Public request, quota, and error boundary for private lineup packets."""

    headless: HeadlessService
    error_message: ErrorMessageLookup
    quotas: PlayerQueryQuotaService | None = None
    requests: PlayerRequestProtectionService | None = None

    async def query(  # noqa: C901, PLR0911 - each external failure has safe wording
        self,
        *,
        player_id: int,
        actor: ActorRef,
        conversation: ConversationRef,
        timeout_seconds: float,
        fetch_packet: PlayerLineupPacketFetcher,
    ) -> PlayerLineupQueryResult:
        from ironsbot.services.seer.ids import (
            PLAYER_ID_ERROR_MESSAGE,
            is_valid_player_id,
        )

        if not is_valid_player_id(player_id):
            return PlayerLineupQueryResult(error=PLAYER_ID_ERROR_MESSAGE)

        def quota_message() -> str:
            if self.quotas is None or actor is None:
                return ""
            decision = self.quotas.check(
                actor=actor,
                player_id=player_id,
                action_key="lineup",
            )
            return "" if decision.allowed else decision.message

        async def fetch() -> PlayerLineupQueryResult:
            if message := quota_message():
                raise PlayerQueryQuotaExceededError(message)
            game = self.headless.get_game()
            observation = ObservationTime()
            with game.operations.track(
                "阵容数据查询",
                f"米米号 {player_id}",
                source="私有阵容插件",
                conversation=conversation,
            ):
                user_info = await observation.observe(
                    lambda: game.get_user_info(player_id)
                )
                payload = await asyncio.wait_for(
                    observation.observe(
                        lambda: fetch_packet(
                            _HeadlessLineupPacketClient(game),
                            player_id,
                            timeout_seconds,
                        )
                    ),
                    timeout=timeout_seconds,
                )
            await self.headless.mark_available(
                source="私有阵容插件",
                user_id=int(game.user_id),
            )
            return PlayerLineupQueryResult(
                leading_text=(
                    "🐾【公开阵容】\n"
                    f"{format_player_data_time(observation.fetched_at)}\n"
                    f"{format_player_identity(player_id, str(user_info.nick))}\n"
                ),
                payload=payload,
            )

        try:
            result = (
                await fetch()
                if self.requests is None
                else await self.requests.run(fetch, actor=actor, label="阵容查询")
            )
        except PlayerQueryQuotaExceededError as error:
            return PlayerLineupQueryResult(error=error.message)
        except (
            PlayerRequestBusyError,
            PlayerRequestPausedError,
            PlayerRequestReconnectError,
        ) as error:
            return PlayerLineupQueryResult(
                error=player_request_protection_message(error)
            )
        except TimeoutError:
            return PlayerLineupQueryResult(
                error=f"❌ 阵容查询超时：米米号 {player_id}。请稍后再试。"
            )
        except (SocketRecvError, NotLoggedInError, DisconnectedError) as error:
            return PlayerLineupQueryResult(
                error=format_player_query_error(player_id, error, self.error_message)
            )
        except Exception:
            logger.exception("private lineup query failed: player_id=%s", player_id)
            return PlayerLineupQueryResult(error="❌ 阵容查询失败，请稍后再试。")

        if self.quotas is not None and actor is not None:
            decision = self.quotas.consume(
                actor=actor,
                player_id=player_id,
                action_key="lineup",
            )
            if not decision.allowed:
                logger.warning(
                    "player lineup quota changed before successful record: "
                    "actor=%s player=%s",
                    actor,
                    player_id,
                )
        return result


@dataclass(frozen=True, slots=True)
class PlayerLineupExtensionServices:
    """Dependencies intentionally available to the player-lineup extension."""

    lineup_entries: PlayerLineupEntryResolver
    lineup_render: PlayerLineupRenderPort
    lineup_query: PlayerLineupQueryPort
    lineup_cache: PlayerLineupCacheFactory
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
