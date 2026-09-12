# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
from math import isfinite
from time import monotonic
from typing import TYPE_CHECKING

from ironsbot.core.semantic_requests import (
    SemanticRequestSource,
)
from ironsbot.core.time import now
from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.services.seer.player_service_models import (
    PendingPlayerQuery,
    _BackgroundRefresh,
    _CachedDetailReply,
)
from ironsbot.services.seer.player_service_support import (
    background_refresh_kinds,
    shortcut_operation_label,
)
from ironsbot.services.seer.player_shortcut_contracts import (
    PlayerShortcutCommand,
    PlayerShortcutDependencies,
    player_shortcut_semantic_request,
)
from ironsbot.services.seer.player_shortcut_queries import fetch_player_shortcut_reply

_BACKGROUND_REFRESH_TIMEOUT_GRACE_SECONDS = 5.0
_PLAYER_DETAIL_TIMEOUT_STAGE_COUNT = 4
PlayerError = SocketRecvError | NotLoggedInError | DisconnectedError

if TYPE_CHECKING:

    from ironsbot.config.models.seer import SeerConfig
    from ironsbot.core.platform import ConversationRef
    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.services.operations.headless import HeadlessGame
    from ironsbot.services.seer.local_rank import LocalRankService
    from ironsbot.services.seer.player_request_protection import (
        PlayerRequestProtectionService,
    )
    from ironsbot.services.seer.player_shortcut_contracts import PlayerShortcutKind
    from ironsbot.services.seer.query_result import QueryReply
    from ironsbot.services.seer.rank import RankService

logger = logging.getLogger(__name__)


class PlayerDetailService:
    def __init__(
        self,
        config: SeerConfig,
        rank: RankService,
        local_rank: LocalRankService,
        spawn: TaskSpawner,
        requests: PlayerRequestProtectionService | None = None,
    ) -> None:
        self._config = config
        self._rank = rank
        self._local_rank = local_rank
        self._spawn = spawn
        self._requests = requests
        self._background_refreshes: dict[int, _BackgroundRefresh] = {}
        self._cached_replies: dict[
            tuple[int, PlayerShortcutKind],
            _CachedDetailReply,
        ] = {}

    def start_background_refresh(
        self,
        game: HeadlessGame,
        pending: PendingPlayerQuery,
        *,
        conversation: ConversationRef | None = None,
    ) -> None:
        refresh_config = self._config.player.background_refresh
        if not refresh_config.enabled:
            return

        kinds = background_refresh_kinds(pending.section_plan)
        if not kinds or pending.player_id in self._background_refreshes:
            return

        self._clear_expired_replies()
        loop = asyncio.get_running_loop()
        refresh = _BackgroundRefresh(
            replies={kind: loop.create_future() for kind in kinds},
            started_at=monotonic(),
            base_snapshot=pending.base_snapshot,
        )
        self._background_refreshes[pending.player_id] = refresh
        task = self._spawn(
            self._run_background_refresh(
                game,
                player_id=pending.player_id,
                refresh=refresh,
                conversation=conversation,
            ),
            name=f"seer-player-background-refresh-{pending.player_id}",
        )
        refresh.task = task
        task.add_done_callback(
            lambda _task: self._finish_background_refresh(pending.player_id, refresh)
        )

    async def shortcut(
        self,
        game: HeadlessGame,
        command: PlayerShortcutCommand,
        player_id: int,
        *,
        use_cache: bool = True,
        anchor_only: bool = False,
    ) -> QueryReply:
        if use_cache:
            cached = self._cached_reply(player_id, command.kind)
            if cached is not None:
                return cached
            refresh = self._background_refreshes.get(player_id)
            pending = None if refresh is None else refresh.replies.get(command.kind)
            if (
                pending is not None
                and not pending.done()
                and refresh is not None
                and refresh.task is not None
                and not refresh.task.done()
            ):
                refreshed = await asyncio.shield(pending)
                if refreshed is not None:
                    return refreshed

        refresh = self._background_refreshes.get(player_id)
        reply = await self._fetch_shortcut(
            game,
            command=command,
            player_id=player_id,
            anchor_only=anchor_only,
        )
        self._store_reply(player_id, command.kind, reply, refresh=refresh)
        return reply

    async def cached_or_inflight_reply(
        self,
        player_id: int,
        kind: PlayerShortcutKind,
    ) -> QueryReply | None:
        if (cached := self._cached_reply(player_id, kind)) is not None:
            return cached
        refresh = self._background_refreshes.get(player_id)
        if refresh is not None and self._refresh_expired(refresh):
            self._expire_background_refresh(player_id, refresh)
            refresh = None
        future = None if refresh is None else refresh.replies.get(kind)
        if future is None or future.done():
            return None
        return (await asyncio.shield(future)) or self._cached_reply(player_id, kind)

    async def _fetch_shortcut(
        self,
        game: HeadlessGame,
        *,
        command: PlayerShortcutCommand,
        player_id: int,
        anchor_only: bool,
    ) -> QueryReply:
        player = self._config.player
        lookup = self._rank.config.player_lookup
        return await fetch_player_shortcut_reply(
            PlayerShortcutDependencies(
                rank=self._rank,
                local_rank=self._local_rank,
                timeout_seconds=min(
                    player.timeout_seconds,
                    player.detail_timeout_seconds / _PLAYER_DETAIL_TIMEOUT_STAGE_COUNT,
                ),
                detail_timeout_seconds=player.detail_timeout_seconds,
                rank_timeout_seconds=(
                    lookup.total_timeout_seconds + lookup.page_timeout_seconds
                ),
            ),
            game,
            command=command,
            player_id=player_id,
            anchor_only=anchor_only,
        )

    async def _run_background_refresh(
        self,
        game: HeadlessGame,
        *,
        player_id: int,
        refresh: _BackgroundRefresh,
        conversation: ConversationRef | None,
    ) -> None:
        await asyncio.gather(
            *(
                self._run_background_refresh_item(
                    game,
                    player_id=player_id,
                    kind=kind,
                    refresh=refresh,
                    conversation=conversation,
                )
                for kind in refresh.replies
            )
        )

    async def _run_background_refresh_item(
        self,
        game: HeadlessGame,
        *,
        player_id: int,
        kind: PlayerShortcutKind,
        refresh: _BackgroundRefresh,
        conversation: ConversationRef | None,
    ) -> None:
        future = refresh.replies[kind]
        if future.done():
            return
        try:
            command = PlayerShortcutCommand(
                kind=kind,
                player_id=player_id,
                base_snapshot=refresh.base_snapshot,
            )
            logger.info(
                "米米号后台预热开始：player_id=%s section=%s",
                player_id,
                kind,
            )
            reply = await self._run_background_shortcut(
                game,
                command=command,
                player_id=player_id,
                conversation=conversation,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "米米号后台预热失败：player_id=%s section=%s",
                player_id,
                kind,
            )
            if not future.done():
                future.set_result(None)
            return

        logger.info(
            "米米号后台预热完成：player_id=%s section=%s",
            player_id,
            kind,
        )
        self._store_reply(player_id, kind, reply, refresh=refresh)

    def _finish_background_refresh(
        self,
        player_id: int,
        refresh: _BackgroundRefresh,
    ) -> None:
        for future in refresh.replies.values():
            if not future.done():
                future.set_result(None)
        if self._background_refreshes.get(player_id) is refresh:
            self._background_refreshes.pop(player_id, None)

    def _cached_reply(
        self,
        player_id: int,
        kind: PlayerShortcutKind,
    ) -> QueryReply | None:
        cache_key = (player_id, kind)
        cached = self._cached_replies.get(cache_key)
        if cached is None:
            return None
        if cached.expires_at > monotonic() and self._cache_remaining(cached.reply) > 0:
            return cached.reply
        self._cached_replies.pop(cache_key, None)
        return None

    def _cache_remaining(self, reply: QueryReply) -> float:
        fetched_at = reply.fetched_at
        if fetched_at is None or not isfinite(fetched_at):
            return 0.0
        age = now().timestamp() - fetched_at
        if age < 0:
            return 0.0
        return self._config.player.background_refresh.cache_ttl_seconds - age

    def _store_reply(
        self,
        player_id: int,
        kind: PlayerShortcutKind,
        reply: QueryReply,
        *,
        refresh: _BackgroundRefresh | None = None,
    ) -> None:
        if (
            refresh is not None
            and self._background_refreshes.get(player_id) is not refresh
        ):
            return
        remaining = self._cache_remaining(reply)
        if reply.complete and remaining > 0:
            self._cached_replies[(player_id, kind)] = _CachedDetailReply(
                expires_at=monotonic() + remaining,
                reply=reply,
            )
        future = None if refresh is None else refresh.replies.get(kind)
        if future is not None and not future.done():
            future.set_result(reply)

    def _clear_expired_replies(self) -> None:
        now = monotonic()
        for cache_key, cached in tuple(self._cached_replies.items()):
            if cached.expires_at <= now:
                self._cached_replies.pop(cache_key, None)

    def has_inflight_refresh(
        self,
        player_id: int,
        kind: PlayerShortcutKind,
    ) -> bool:
        refresh = self._background_refreshes.get(player_id)
        if refresh is not None and self._refresh_expired(refresh):
            self._expire_background_refresh(player_id, refresh)
            return False
        future = None if refresh is None else refresh.replies.get(kind)
        return future is not None and not future.done()

    async def _run_background_shortcut(
        self,
        game: HeadlessGame,
        *,
        command: PlayerShortcutCommand,
        player_id: int,
        conversation: ConversationRef | None,
    ) -> QueryReply:
        async def fetch() -> QueryReply:
            with game.operations.track(
                shortcut_operation_label(command.kind),
                f"米米号 {player_id}",
                source="米米号后台预热",
                background=True,
                conversation=conversation,
            ):
                return await self._fetch_shortcut(
                    game,
                    command=command,
                    player_id=player_id,
                    anchor_only=False,
                )

        timeout_seconds = self._background_refresh_timeout_seconds()
        if self._requests is None:
            return await asyncio.wait_for(fetch(), timeout=timeout_seconds)
        return await self._requests.run(
            fetch,
            actor=None,
            label=f"后台{shortcut_operation_label(command.kind)}",
            background=True,
            timeout_seconds=timeout_seconds,
            semantic_request=player_shortcut_semantic_request(
                kind=command.kind,
                player_id=player_id,
                source=SemanticRequestSource.BACKGROUND,
            ),
        )

    def _background_refresh_timeout_seconds(self) -> float:
        return (
            float(self._config.player.detail_timeout_seconds)
            + _BACKGROUND_REFRESH_TIMEOUT_GRACE_SECONDS
        )

    def _refresh_expired(self, refresh: _BackgroundRefresh) -> bool:
        return (
            monotonic() - refresh.started_at
            >= self._background_refresh_timeout_seconds()
        )

    def _expire_background_refresh(
        self,
        player_id: int,
        refresh: _BackgroundRefresh,
    ) -> None:
        logger.warning(
            "米米号后台预热超时，清理等待状态：player_id=%s",
            player_id,
        )
        self._finish_background_refresh(player_id, refresh)
        if refresh.task is not None and not refresh.task.done():
            refresh.task.cancel()
