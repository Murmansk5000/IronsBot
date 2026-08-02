# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
from time import monotonic
from typing import TYPE_CHECKING, Any

from ironsbot.core.semantic_requests import (
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    SemanticTarget,
)
from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.services.operations.headless_pool import HeadlessRequestPriority
from ironsbot.services.seer.errors import format_player_query_error
from ironsbot.services.seer.ids import (
    PLAYER_ID_ERROR_MESSAGE,
    is_valid_player_id,
)
from ironsbot.services.seer.player_account_policy import PlayerAccountPolicyMixin
from ironsbot.services.seer.player_basic_query import fetch_pending_player_query
from ironsbot.services.seer.player_binding import player_binding_offer_message
from ironsbot.services.seer.player_messages import unbound_player_shortcut_message
from ironsbot.services.seer.player_profile_cache import NullPlayerProfileCache
from ironsbot.services.seer.player_query import (
    player_query_failure_message,
    player_query_timeout_message,
)
from ironsbot.services.seer.player_query_cache import PlayerQueryCache
from ironsbot.services.seer.player_query_limits import (
    PlayerQueryQuotaExceededError,
)
from ironsbot.services.seer.player_request_protection import (
    player_request_protection_message,
)
from ironsbot.services.seer.player_service_models import (
    PendingPlayerQuery,
    PlayerQueryResult,
    _BackgroundRefresh,
    _CachedDetailReply,
)
from ironsbot.services.seer.player_service_support import (
    PLAYER_REQUEST_ERRORS,
    background_refresh_kinds,
    shortcut_operation_label,
    utc_now,
)
from ironsbot.services.seer.player_shortcuts import (
    PlayerShortcutCommand,
    PlayerShortcutDependencies,
    fetch_player_shortcut_reply,
    player_shortcut_semantic_request,
)
from ironsbot.services.seer.query_result import QueryReply

_BACKGROUND_REFRESH_TIMEOUT_GRACE_SECONDS = 5.0
_PLAYER_DETAIL_TIMEOUT_STAGE_COUNT = 4

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime

    from ironsbot.config.models.seer import SeerConfig
    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.services.operations.headless import HeadlessGame, HeadlessService
    from ironsbot.services.seer.errors import ErrorMessageLookup
    from ironsbot.services.seer.local_rank import LocalRankService
    from ironsbot.services.seer.player_binding import PlayerBindingStore
    from ironsbot.services.seer.player_profile_cache import PlayerProfileCache
    from ironsbot.services.seer.player_query_limits import PlayerQueryQuotaService
    from ironsbot.services.seer.player_request_protection import (
        PlayerRequestProtectionService,
    )
    from ironsbot.services.seer.player_shortcuts import PlayerShortcutKind
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
        group_id: int | None = None,
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
        )
        self._background_refreshes[pending.player_id] = refresh
        task = self._spawn(
            self._run_background_refresh(
                game,
                player_id=pending.player_id,
                refresh=refresh,
                group_id=group_id,
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

        reply = await self._fetch_shortcut(
            game,
            command=command,
            player_id=player_id,
            anchor_only=anchor_only,
        )
        self._store_reply(player_id, command.kind, reply)
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
        if future is None:
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
        return await fetch_player_shortcut_reply(
            PlayerShortcutDependencies(
                rank=self._rank,
                local_rank=self._local_rank,
                timeout_seconds=self._detail_stage_timeout_seconds(),
            ),
            game,
            command=command,
            player_id=player_id,
            anchor_only=anchor_only,
        )

    def _detail_stage_timeout_seconds(self) -> float:
        player_config = self._config.player
        basic_timeout = float(getattr(player_config, "timeout_seconds", 30.0))
        detail_timeout = float(
            getattr(player_config, "detail_timeout_seconds", 90.0)
        )
        return min(
            basic_timeout,
            detail_timeout / _PLAYER_DETAIL_TIMEOUT_STAGE_COUNT,
        )

    async def _run_background_refresh(
        self,
        game: HeadlessGame,
        *,
        player_id: int,
        refresh: _BackgroundRefresh,
        group_id: int | None,
    ) -> None:
        for kind, future in refresh.replies.items():
            await self._run_background_refresh_item(
                game,
                player_id=player_id,
                kind=kind,
                future=future,
                group_id=group_id,
            )

    async def _run_background_refresh_item(
        self,
        game: HeadlessGame,
        *,
        player_id: int,
        kind: PlayerShortcutKind,
        future: asyncio.Future[QueryReply | None],
        group_id: int | None,
    ) -> None:
        if future.done():
            return
        try:
            command = PlayerShortcutCommand(kind=kind, player_id=player_id)
            logger.info(
                "米米号后台预热开始：player_id=%s section=%s",
                player_id,
                kind,
            )
            reply = await self._run_background_shortcut(
                game,
                command=command,
                player_id=player_id,
                group_id=group_id,
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
        self._store_reply(player_id, kind, reply)

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
        if cached.expires_at > monotonic():
            return cached.reply
        self._cached_replies.pop(cache_key, None)
        return None

    def _store_reply(
        self,
        player_id: int,
        kind: PlayerShortcutKind,
        reply: QueryReply,
    ) -> None:
        self._cached_replies[(player_id, kind)] = _CachedDetailReply(
            expires_at=monotonic()
            + self._config.player.background_refresh.cache_ttl_seconds,
            reply=reply,
        )
        refresh = self._background_refreshes.get(player_id)
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
        group_id: int | None,
    ) -> QueryReply:
        async def fetch() -> QueryReply:
            with game.operations.track(
                shortcut_operation_label(command.kind),
                f"米米号 {player_id}",
                source="米米号后台预热",
                background=True,
                group_id=group_id,
            ):
                return await asyncio.wait_for(
                    self._fetch_shortcut(
                        game,
                        command=command,
                        player_id=player_id,
                        anchor_only=False,
                    ),
                    timeout=self._config.player.detail_timeout_seconds,
                )

        timeout_seconds = self._background_refresh_timeout_seconds()
        if self._requests is None:
            return await asyncio.wait_for(fetch(), timeout=timeout_seconds)
        return await self._requests.run(
            fetch,
            user_id=None,
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
        for future in refresh.replies.values():
            if not future.done():
                future.set_result(None)
        if self._background_refreshes.get(player_id) is refresh:
            self._background_refreshes.pop(player_id, None)


class PlayerService(PlayerAccountPolicyMixin):
    def __init__(  # noqa: PLR0913 - composed Seer query dependencies
        self,
        config: SeerConfig,
        headless: HeadlessService,
        bindings: PlayerBindingStore,
        error_message: ErrorMessageLookup,
        details: PlayerDetailService,
        quotas: PlayerQueryQuotaService | None = None,
        requests: PlayerRequestProtectionService | None = None,
        *,
        profile_cache: PlayerProfileCache | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._headless = headless
        self._bindings = bindings
        self._error_message = error_message
        self._details = details
        self._profile_cache = profile_cache or NullPlayerProfileCache()
        self._quotas = quotas
        self._requests = requests
        self._now = now or utc_now
        self._query_cache = PlayerQueryCache.from_config(config)

    def default_player_id(self, qq_user_id: int) -> int | None:
        return self._bindings.get(qq_user_id).player_id

    async def query(
        self,
        player_id: int,
        *,
        qq_user_id: int,
        explicit: bool,
        group_id: int | None = None,
    ) -> PlayerQueryResult:
        if not is_valid_player_id(player_id):
            return PlayerQueryResult(message=PLAYER_ID_ERROR_MESSAGE)
        binding = self._bindings.get(qq_user_id)
        cached = self._query_cache.result(
            player_id,
            offer_binding=explicit and not binding.choice_completed,
        )
        quota_message = self._check_quota(
            qq_user_id=qq_user_id,
            player_id=player_id,
            action_key="player",
        )
        if quota_message:
            return cached or PlayerQueryResult(message=quota_message)
        try:
            result = await self._run_live_request(
                lambda: self._query(
                    player_id,
                    source="米米号查询",
                    group_id=group_id,
                ),
                user_id=qq_user_id,
                label="米米号基础资料",
                quota_player_id=player_id,
                quota_action_key="player",
                semantic_request=SemanticRequest(
                    action=ActionDefinition(
                        "seer.player.info",
                        "米米号基础资料",
                        cooldown_key="seer_player",
                    ),
                    target=SemanticTarget(
                        key=str(player_id),
                        display=f"米米号 {player_id}",
                    ),
                    source=SemanticRequestSource.DIRECT,
                ),
                priority=HeadlessRequestPriority.BASIC,
            )
        except PlayerQueryQuotaExceededError as error:
            return cached or PlayerQueryResult(message=error.message)
        except PLAYER_REQUEST_ERRORS as error:
            return cached or PlayerQueryResult(
                message=player_request_protection_message(error)
            )
        if result.pending is None:
            return cached or result
        self._query_cache.put(result.pending)
        binding = self._bindings.get(qq_user_id)
        return PlayerQueryResult(
            pending=result.pending,
            offer_binding=explicit and not binding.choice_completed,
        )

    async def bind_player(
        self,
        player_id: int,
        *,
        qq_user_id: int,
        group_id: int | None = None,
    ) -> PlayerQueryResult:
        """Validate a player ID, save it as default, and return its info."""
        result = await self.query(
            player_id,
            qq_user_id=qq_user_id,
            explicit=True,
            group_id=group_id,
        )
        if result.message or result.pending is None:
            return result

        pending = result.pending
        status = self._save_binding(qq_user_id, pending)
        pending.player_message = f"{status}\n\n{pending.player_message}"
        return PlayerQueryResult(pending=pending)

    def save_binding_choice(
        self,
        qq_user_id: int,
        pending: PendingPlayerQuery,
        *,
        accepted: bool,
    ) -> str:
        if accepted:
            status = self._save_binding(qq_user_id, pending)
        else:
            try:
                self._bindings.decline(qq_user_id=qq_user_id)
                status = "已跳过默认米米号设置。"
            except Exception as error:
                logger.exception("保存米米号绑定选择失败")
                status = f"⚠️ 默认米米号设置保存失败：{error}"
        pending.player_message = f"{status}\n\n{pending.player_message}"
        return status

    def binding_offer(self, pending: PendingPlayerQuery) -> str:
        limits = self._config.player.query_limits
        return player_binding_offer_message(
            pending.player_id,
            str(pending.user_info.nick),
            unbound_daily_limit=(
                limits.unbound_daily_limit if limits.enabled else None
            ),
            bound_default_daily_limit=(
                limits.bound_default_daily_limit if limits.enabled else None
            ),
        )

    def record_returned_query(
        self,
        qq_user_id: int,
        pending: PendingPlayerQuery,
    ) -> None:
        if pending.quota_recorded:
            return
        pending.quota_recorded = True
        try:
            self._record_successful_quota(
                qq_user_id=qq_user_id,
                player_id=pending.player_id,
                action_key="player",
            )
        except Exception:
            logger.exception(
                "记录已返回的米米号查询额度失败：user=%s player=%s",
                qq_user_id,
                pending.player_id,
            )

    def start_background_refresh(
        self,
        pending: PendingPlayerQuery,
        *,
        group_id: int | None = None,
    ) -> None:
        """Begin optional detail prefetch only after the initial reply is sent."""
        try:
            game = self._headless.get_game()
        except (NotLoggedInError, DisconnectedError):
            logger.info(
                "跳过米米号后台预热：无头客户端当前不可用 player_id=%s",
                pending.player_id,
            )
            return
        self._details.start_background_refresh(
            game,
            pending,
            group_id=group_id,
        )

    def unbind(self, qq_user_id: int) -> str:
        binding = self._bindings.get(qq_user_id)
        if binding.player_id is None:
            return "当前没有已绑定的米米号。"
        change_error = self._binding_change_error(qq_user_id)
        if change_error:
            return change_error
        removed = self._bindings.unbind(
            qq_user_id=qq_user_id,
            changed_at=self._now(),
        )
        return "已解除默认米米号。" if removed else "当前没有已绑定的米米号。"

    async def shortcut(  # noqa: C901, PLR0911 - distinct query failure replies
        self,
        command: PlayerShortcutCommand,
        qq_user_id: int,
        *,
        group_id: int | None = None,
    ) -> QueryReply:
        player_id = command.player_id or self.default_player_id(qq_user_id)
        if player_id is None:
            return QueryReply(text=unbound_player_shortcut_message())
        if not is_valid_player_id(player_id):
            return QueryReply(text=PLAYER_ID_ERROR_MESSAGE)
        cached = await self._details.cached_or_inflight_reply(
            player_id,
            command.kind,
        )
        if cached is not None:
            return cached
        try:
            quota_message = self._check_quota(
                qq_user_id=qq_user_id,
                player_id=player_id,
                action_key=command.kind,
            )
            anchor_only = bool(quota_message)
            message = await self._run_live_request(
                lambda: self._shortcut_live(
                    command,
                    player_id,
                    group_id=group_id,
                    anchor_only=anchor_only,
                ),
                user_id=qq_user_id,
                label=shortcut_operation_label(command.kind),
                quota_player_id=player_id,
                quota_action_key=command.kind,
                allow_quota_exhausted=anchor_only,
                semantic_request=player_shortcut_semantic_request(
                    kind=command.kind,
                    player_id=player_id,
                    source=SemanticRequestSource.DIRECT,
                ),
            )
        except PlayerQueryQuotaExceededError as error:
            return QueryReply(text=error.message)
        except PLAYER_REQUEST_ERRORS as error:
            return QueryReply(text=player_request_protection_message(error))
        except (TimeoutError, asyncio.TimeoutError):
            return QueryReply(text=player_query_timeout_message(player_id))
        except (SocketRecvError, NotLoggedInError, DisconnectedError) as error:
            return QueryReply(text=self.format_error(player_id, error))
        except Exception as error:  # noqa: BLE001
            return QueryReply(
                text=player_query_failure_message(player_id, error)
            )
        if quota_message:
            if not message.rank_lookup_is_lightweight:
                return QueryReply(text=quota_message)
            return message
        if message.rank_lookup_should_charge_quota:
            self._record_successful_quota(
                qq_user_id=qq_user_id,
                player_id=player_id,
                action_key=command.kind,
            )
        return message

    def has_inflight_detail(
        self,
        player_id: int,
        kind: PlayerShortcutKind,
    ) -> bool:
        return self._details.has_inflight_refresh(player_id, kind)

    async def _shortcut_live(
        self,
        command: PlayerShortcutCommand,
        player_id: int,
        *,
        group_id: int | None,
        anchor_only: bool,
    ) -> QueryReply:
        game = self._headless.get_game()
        with game.operations.track(
            shortcut_operation_label(command.kind),
            f"米米号 {player_id}",
            source="米米号快捷详情查询",
            group_id=group_id,
        ):
            message = await asyncio.wait_for(
                self._details.shortcut(
                    game,
                    command,
                    player_id,
                    use_cache=False,
                    anchor_only=anchor_only,
                ),
                timeout=self._config.player.detail_timeout_seconds,
            )
        await self._headless.mark_available(
            source="米米号快捷详情查询",
            user_id=int(game.user_id),
        )
        return message

    def format_error(
        self,
        player_id: int,
        error: SocketRecvError | NotLoggedInError | DisconnectedError,
    ) -> str:
        return format_player_query_error(
            player_id,
            error,
            self._error_message,
        )

    async def _query(
        self,
        player_id: int,
        *,
        source: str,
        group_id: int | None,
    ) -> PlayerQueryResult:
        try:
            game = self._headless.get_game()
            pending = await fetch_pending_player_query(
                self._config,
                player_id,
                game,
                group_id=group_id,
                profile_cache=self._profile_cache,
            )
            await self._headless.mark_available(
                source=source,
                user_id=int(game.user_id),
            )
            return PlayerQueryResult(pending=pending)
        except (TimeoutError, asyncio.TimeoutError):
            return PlayerQueryResult(
                message=player_query_timeout_message(player_id)
            )
        except (SocketRecvError, NotLoggedInError, DisconnectedError) as error:
            if isinstance(error, (NotLoggedInError, DisconnectedError)):
                await self._headless.mark_unavailable(
                    str(error),
                    source=source,
                )
            return PlayerQueryResult(message=self.format_error(player_id, error))
        except Exception as error:
            logger.exception(
                "米米号查询失败：player_id=%s source=%s",
                player_id,
                source,
            )
            return PlayerQueryResult(
                message=player_query_failure_message(player_id, error)
            )

    async def _run_live_request(  # noqa: PLR0913
        self,
        operation: Callable[[], Awaitable[Any]],
        *,
        user_id: int,
        label: str,
        quota_player_id: int | None = None,
        quota_action_key: str | None = None,
        semantic_request: SemanticRequest | None = None,
        allow_quota_exhausted: bool = False,
        priority: HeadlessRequestPriority | None = None,
    ) -> Any:
        async def guarded_operation() -> Any:
            if quota_player_id is not None and quota_action_key is not None:
                quota_message = self._check_quota(
                    qq_user_id=user_id,
                    player_id=quota_player_id,
                    action_key=quota_action_key,
                )
                if quota_message and not allow_quota_exhausted:
                    raise PlayerQueryQuotaExceededError(quota_message)
            return await operation()
        if self._requests is None:
            return await guarded_operation()
        return await self._requests.run(
            guarded_operation,
            user_id=user_id,
            label=label,
            semantic_request=semantic_request,
            priority=priority,
        )
