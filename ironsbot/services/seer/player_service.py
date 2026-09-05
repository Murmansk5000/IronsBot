# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
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
from ironsbot.services.operations.request_feedback import send_request_feedback
from ironsbot.services.seer.errors import format_player_query_error
from ironsbot.services.seer.ids import (
    PLAYER_ID_ERROR_MESSAGE,
    is_valid_player_id,
)
from ironsbot.services.seer.player_account_policy import PlayerAccountPolicyMixin
from ironsbot.services.seer.player_basic_query import fetch_pending_player_query
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
)
from ironsbot.services.seer.player_service_support import (
    PLAYER_REQUEST_ERRORS,
    shortcut_operation_label,
    utc_now,
)
from ironsbot.services.seer.player_shortcut_contracts import (
    PlayerShortcutCommand,
    player_shortcut_semantic_request,
)
from ironsbot.services.seer.query_result import QueryReply

_BACKGROUND_REFRESH_TIMEOUT_GRACE_SECONDS = 5.0
_PLAYER_DETAIL_TIMEOUT_STAGE_COUNT = 4
PlayerError = SocketRecvError | NotLoggedInError | DisconnectedError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime

    from ironsbot.config.models.seer import SeerConfig
    from ironsbot.core.platform import ActorRef, ConversationRef
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.seer.errors import ErrorMessageLookup
    from ironsbot.services.seer.player_binding import PlayerBindingStore
    from ironsbot.services.seer.player_detail_service import PlayerDetailService
    from ironsbot.services.seer.player_profile_cache import PlayerProfileCache
    from ironsbot.services.seer.player_query_limits import PlayerQueryQuotaService
    from ironsbot.services.seer.player_request_protection import (
        PlayerRequestProtectionService,
    )
    from ironsbot.services.seer.player_shortcut_contracts import PlayerShortcutKind

logger = logging.getLogger(__name__)


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

    def default_player_id(self, actor: ActorRef) -> int | None:
        return self._bindings.get(actor).player_id

    async def query(
        self,
        player_id: int,
        *,
        actor: ActorRef,
        explicit: bool,
        conversation: ConversationRef | None = None,
    ) -> PlayerQueryResult:
        if not is_valid_player_id(player_id):
            return PlayerQueryResult(message=PLAYER_ID_ERROR_MESSAGE)
        binding = self._bindings.get(actor)
        cached = self._query_cache.result(
            player_id,
            offer_binding=explicit and not binding.choice_completed,
        )
        quota_message = self._check_quota(
            actor=actor,
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
                    conversation=conversation,
                ),
                actor=actor,
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
        binding = self._bindings.get(actor)
        return PlayerQueryResult(
            pending=result.pending,
            offer_binding=explicit and not binding.choice_completed,
        )

    async def bind_player(
        self,
        player_id: int,
        *,
        actor: ActorRef,
        conversation: ConversationRef | None = None,
    ) -> PlayerQueryResult:
        """Validate a player ID, save it as default, and return its info."""
        binding = self._bindings.get(actor)
        if binding.player_id == player_id:
            nick = f"（{binding.player_nick}）" if binding.player_nick else ""
            return PlayerQueryResult(
                message=f"当前已绑定该米米号：{player_id}{nick}。"
            )
        if binding.player_id is not None:
            change_error = self._binding_change_error(actor)
            if change_error:
                return PlayerQueryResult(message=change_error)
        result = await self.query(
            player_id,
            actor=actor,
            explicit=True,
            conversation=conversation,
        )
        if result.message or result.pending is None:
            return result

        pending = result.pending
        if binding.player_id is not None:
            return PlayerQueryResult(
                pending=pending,
                offer_binding=True,
                binding_replacement=binding,
            )
        status = self._save_binding(actor, pending)
        pending.player_message = f"{status}\n\n{pending.player_message}"
        return PlayerQueryResult(pending=pending)

    def record_returned_query(
        self,
        actor: ActorRef,
        pending: PendingPlayerQuery,
    ) -> None:
        if pending.quota_recorded:
            return
        pending.quota_recorded = True
        try:
            self._record_successful_quota(
                actor=actor,
                player_id=pending.player_id,
                action_key="player",
            )
        except Exception:
            logger.exception(
                "记录已返回的米米号查询额度失败：user=%s player=%s",
                actor.id,
                pending.player_id,
            )

    def start_background_refresh(
        self,
        pending: PendingPlayerQuery,
        *,
        conversation: ConversationRef | None = None,
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
            conversation=conversation,
        )

    def unbind(self, actor: ActorRef) -> str:
        binding = self._bindings.get(actor)
        if binding.player_id is None:
            return "当前没有已绑定的米米号。"
        change_error = self._binding_change_error(actor)
        if change_error:
            return change_error
        removed = self._bindings.unbind(
            actor=actor,
            changed_at=self._now(),
        )
        return "已解除默认米米号。" if removed else "当前没有已绑定的米米号。"

    async def shortcut(  # noqa: C901, PLR0911 - distinct query failure replies
        self,
        command: PlayerShortcutCommand,
        actor: ActorRef,
        *,
        conversation: ConversationRef | None = None,
    ) -> QueryReply:
        player_id = command.player_id
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
                actor=actor,
                player_id=player_id,
                action_key=command.kind,
            )
            anchor_only = bool(quota_message)
            message = await self._run_live_request(
                lambda: self._shortcut_live(
                    command,
                    player_id,
                    conversation=conversation,
                    anchor_only=anchor_only,
                ),
                actor=actor,
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
                actor=actor,
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
        conversation: ConversationRef | None,
        anchor_only: bool,
    ) -> QueryReply:
        game = self._headless.get_game()
        with game.operations.track(
            shortcut_operation_label(command.kind),
            f"米米号 {player_id}",
            source="米米号快捷详情查询",
            conversation=conversation,
        ):
            message = await self._details.shortcut(
                game,
                command,
                player_id,
                use_cache=False,
                anchor_only=anchor_only,
            )
        await self._headless.mark_available(
            source="米米号快捷详情查询",
            user_id=int(game.user_id),
        )
        return message

    def format_error(self, player_id: int, error: PlayerError) -> str:
        return format_player_query_error(player_id, error, self._error_message)

    async def _query(
        self,
        player_id: int,
        *,
        source: str,
        conversation: ConversationRef | None,
    ) -> PlayerQueryResult:
        try:
            game = self._headless.get_game()
            pending = await fetch_pending_player_query(
                self._config,
                player_id,
                game,
                conversation=conversation,
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
        actor: ActorRef,
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
                    actor=actor,
                    player_id=quota_player_id,
                    action_key=quota_action_key,
                )
                if quota_message and not allow_quota_exhausted:
                    raise PlayerQueryQuotaExceededError(quota_message)
            return await operation()
        if self._requests is None:
            await send_request_feedback(queued=False)
            return await guarded_operation()
        return await self._requests.run(
            guarded_operation,
            actor=actor,
            label=label,
            semantic_request=semantic_request,
            priority=priority,
        )
