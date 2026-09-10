# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
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
from ironsbot.services.seer.player_detail_service import (
    PlayerDetailService,  # noqa: TC001 - compatibility export
)
from ironsbot.services.seer.player_messages import unbound_player_shortcut_message
from ironsbot.services.seer.player_profile_cache import NullPlayerProfileCache
from ironsbot.services.seer.player_query import (
    player_query_failure_message,
    player_query_timeout_message,
)
from ironsbot.services.seer.player_query_cache import PlayerQueryCache
from ironsbot.services.seer.player_request_execution import run_player_live_request
from ironsbot.services.seer.player_request_protection import (
    player_request_protection_message,
)
from ironsbot.services.seer.player_service_models import (
    PendingPlayerQuery,
    PlayerQueryResult,
    _BackgroundRefresh,  # noqa: F401 - compatibility export
)
from ironsbot.services.seer.player_service_support import (
    PLAYER_REQUEST_ERRORS,
    shortcut_operation_label,
    shortcut_timeout_seconds,
    utc_now,
)
from ironsbot.services.seer.player_shortcuts import (
    PlayerShortcutCommand,
    player_shortcut_semantic_request,
)
from ironsbot.services.seer.query_result import QueryReply
from ironsbot.services.seer.query_work import (
    QueryWorkMeter,
    run_with_query_work,
)

_BACKGROUND_REFRESH_TIMEOUT_GRACE_SECONDS = 5.0
_PLAYER_DETAIL_TIMEOUT_STAGE_COUNT = 4

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from ironsbot.config.models.seer import SeerConfig
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.seer.errors import ErrorMessageLookup
    from ironsbot.services.seer.player_binding import PlayerBindingStore
    from ironsbot.services.seer.player_profile_cache import PlayerProfileCache
    from ironsbot.services.seer.player_query_limits import PlayerQueryQuotaService
    from ironsbot.services.seer.player_request_protection import (
        PlayerRequestProtectionService,
    )
    from ironsbot.services.seer.player_shortcuts import PlayerShortcutKind

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
        superuser_ids: frozenset[int] = frozenset(),
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
        self._superuser_ids = superuser_ids
        self._query_cache = PlayerQueryCache.from_config(config)

    def default_player_id(self, qq_user_id: int) -> int | None:
        return self._bindings.get(qq_user_id).player_id

    def shortcut_target_access_error(
        self,
        requester_user_id: int,
        player_id: int,
    ) -> str | None:
        """Hide superuser-bound accounts from indirect shortcut lookups."""

        if not self._config.player.binding.protect_superuser_bound_shortcuts:
            return None
        for superuser_id in self._superuser_ids:
            if superuser_id == requester_user_id:
                continue
            if self.default_player_id(superuser_id) == player_id:
                return "该米米号不支持快捷查询，请使用完整数字米米号。"
        return None

    async def query(
        self,
        player_id: int,
        *,
        qq_user_id: int,
        explicit: bool,
        group_id: int | None = None,
        allow_quota_exhausted: bool = False,
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
        if quota_message and not allow_quota_exhausted:
            return cached or PlayerQueryResult(message=quota_message)
        meter = QueryWorkMeter("foreground")

        try:
            result = await run_player_live_request(
                self._requests,
                lambda: run_with_query_work(
                    meter,
                    self._query(
                        player_id,
                        source="米米号查询",
                        group_id=group_id,
                    ),
                ),
                user_id=qq_user_id,
                label="米米号基础资料",
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
        except PLAYER_REQUEST_ERRORS as error:
            return cached or PlayerQueryResult(
                message=player_request_protection_message(error)
            )
        if result.pending is None:
            return cached or result
        result.pending.query_work = meter.result()
        if not result.pending.query_work.successful_units:
            # Test doubles and extension implementations may provide an already
            # built pending reply. A live pending reply still represents one
            # successful basic-info operation.
            meter.succeeded("profile")
            result.pending.query_work = meter.result()
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
        binding = self._bindings.get(qq_user_id)
        if binding.player_id == player_id:
            nick = f"（{binding.player_nick}）" if binding.player_nick else ""
            return PlayerQueryResult(
                message=f"当前已绑定该米米号：{player_id}{nick}。"
            )
        if binding.player_id is not None:
            change_error = self._binding_change_error(qq_user_id)
            if change_error:
                return PlayerQueryResult(message=change_error)
        query_kwargs: dict[str, Any] = {
            "qq_user_id": qq_user_id,
            "explicit": True,
            "group_id": group_id,
        }
        if getattr(self, "_quotas", None) is not None and self._check_quota(
            qq_user_id=qq_user_id,
            player_id=player_id,
            action_key="player",
        ):
            query_kwargs["allow_quota_exhausted"] = True
        result = await self.query(player_id, **query_kwargs)
        if result.message or result.pending is None:
            return result

        pending = result.pending
        if binding.player_id is not None:
            return PlayerQueryResult(
                pending=pending,
                offer_binding=True,
                binding_replacement=binding,
            )
        status = self._save_binding(qq_user_id, pending)
        pending.player_message = f"{status}\n\n{pending.player_message}"
        return PlayerQueryResult(pending=pending)

    def record_returned_query(
        self,
        qq_user_id: int,
        pending: PendingPlayerQuery,
    ) -> None:
        if pending.quota_recorded:
            return
        pending.quota_recorded = True
        try:
            work = pending.query_work
            self._settle_query_work(
                qq_user_id=qq_user_id,
                player_id=pending.player_id,
                action_key="player",
                units=(frozenset() if work is None else work.billable_units),
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

    async def shortcut(  # noqa: PLR0911 - distinct query failure replies
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
            player_id, command.kind, wait_for_inflight=False
        )
        if cached is not None:
            return cached
        meter = QueryWorkMeter("foreground")

        try:
            quota_message = self._check_quota(
                qq_user_id=qq_user_id,
                player_id=player_id,
                action_key=command.kind,
            )
            if quota_message:
                return QueryReply(text=quota_message)
            message = await run_player_live_request(
                self._requests,
                lambda: run_with_query_work(
                    meter,
                    self._shortcut_live(
                        command,
                        player_id,
                        group_id=group_id,
                        anchor_only=False,
                    ),
                ),
                user_id=qq_user_id,
                label=shortcut_operation_label(command.kind),
                semantic_request=player_shortcut_semantic_request(
                    kind=command.kind,
                    player_id=player_id,
                    source=SemanticRequestSource.DIRECT,
                ),
            )
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
        return replace(message, query_work=meter.result())

    def record_returned_shortcut(
        self,
        qq_user_id: int,
        command: PlayerShortcutCommand,
        reply: QueryReply,
    ) -> None:
        player_id = command.player_id or self.default_player_id(qq_user_id)
        if player_id is None or reply.query_work is None:
            return
        self.record_returned_detail_reply(
            qq_user_id=qq_user_id,
            player_id=player_id,
            action_key=command.kind,
            reply=reply,
        )

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
                timeout=shortcut_timeout_seconds(self._config, command.kind),
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
