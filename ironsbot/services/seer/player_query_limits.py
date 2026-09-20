# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Literal, Protocol

from ironsbot.core.time import TZ_CN

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.core.platform import ActorRef
    from ironsbot.services.seer.player_binding import PlayerBindingStore

PlayerQueryQuotaScope = Literal["bound_default", "bound_other", "unbound"]


class PlayerQueryQuotaExceededError(RuntimeError):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PlayerQueryUsage:
    allowed: bool
    used_count: int
    limit: int


class PlayerQueryLimitStore(Protocol):
    def status(  # noqa: PLR0913
        self,
        *,
        local_date: date,
        actor: ActorRef,
        scope: PlayerQueryQuotaScope,
        player_id: int,
        action_key: str,
        limit: int,
    ) -> PlayerQueryUsage: ...

    def consume(  # noqa: PLR0913
        self,
        *,
        local_date: date,
        actor: ActorRef,
        scope: PlayerQueryQuotaScope,
        player_id: int,
        action_key: str,
        limit: int,
    ) -> PlayerQueryUsage: ...


class SuperuserLookup(Protocol):
    def is_actor_superuser(self, actor: ActorRef) -> bool: ...


class PlayerQueryLimitsConfig(Protocol):
    enabled: bool
    bound_default_daily_limit: int
    bound_other_daily_limit: int
    unbound_daily_limit: int
    superuser_bypass: bool


@dataclass(frozen=True, slots=True)
class PlayerQueryQuotaDecision:
    allowed: bool
    message: str = ""


class PlayerQueryQuotaService:
    """Apply persistent daily budgets only after a live lookup succeeds."""

    def __init__(
        self,
        config: PlayerQueryLimitsConfig,
        bindings: PlayerBindingStore,
        features: SuperuserLookup,
        store: PlayerQueryLimitStore,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._bindings = bindings
        self._features = features
        self._store = store
        self._now = now or _now_cn

    def check(
        self,
        *,
        actor: ActorRef,
        player_id: int,
        action_key: str,
    ) -> PlayerQueryQuotaDecision:
        if not self._config.enabled:
            return PlayerQueryQuotaDecision(allowed=True)
        if self._config.superuser_bypass and self._features.is_actor_superuser(actor):
            return PlayerQueryQuotaDecision(allowed=True)

        scope, storage_player_id, storage_action_key, limit = self._quota_key(
            actor=actor,
            player_id=player_id,
            action_key=action_key,
        )
        usage = self._store.status(
            local_date=self._now().date(),
            actor=actor,
            scope=scope,
            player_id=storage_player_id,
            action_key=storage_action_key,
            limit=limit,
        )
        if usage.allowed:
            return PlayerQueryQuotaDecision(allowed=True)
        return PlayerQueryQuotaDecision(
            allowed=False,
            message=_quota_exhausted_message(
                scope=scope,
                player_id=player_id,
                limit=usage.limit,
                bound_default_daily_limit=(self._config.bound_default_daily_limit),
            ),
        )

    def consume(
        self,
        *,
        actor: ActorRef,
        player_id: int,
        action_key: str,
    ) -> PlayerQueryQuotaDecision:
        if not self._config.enabled:
            return PlayerQueryQuotaDecision(allowed=True)
        if self._config.superuser_bypass and self._features.is_actor_superuser(actor):
            return PlayerQueryQuotaDecision(allowed=True)

        scope, storage_player_id, storage_action_key, limit = self._quota_key(
            actor=actor,
            player_id=player_id,
            action_key=action_key,
        )
        usage = self._store.consume(
            local_date=self._now().date(),
            actor=actor,
            scope=scope,
            player_id=storage_player_id,
            action_key=storage_action_key,
            limit=limit,
        )
        if usage.allowed:
            return PlayerQueryQuotaDecision(allowed=True)
        return PlayerQueryQuotaDecision(
            allowed=False,
            message=_quota_exhausted_message(
                scope=scope,
                player_id=player_id,
                limit=usage.limit,
                bound_default_daily_limit=(self._config.bound_default_daily_limit),
            ),
        )

    def _quota_key(
        self,
        *,
        actor: ActorRef,
        player_id: int,
        action_key: str,
    ) -> tuple[PlayerQueryQuotaScope, int, str, int]:
        binding = self._bindings.get(actor)
        if binding.player_id is None:
            return (
                "unbound",
                0,
                "all",
                self._config.unbound_daily_limit,
            )
        if binding.player_id == player_id:
            return (
                "bound_default",
                0,
                "all",
                self._config.bound_default_daily_limit,
            )
        return (
            "bound_other",
            player_id,
            action_key,
            self._config.bound_other_daily_limit,
        )


def _now_cn() -> datetime:
    return datetime.now(TZ_CN)


def _quota_exhausted_message(
    *,
    scope: PlayerQueryQuotaScope,
    player_id: int,
    limit: int,
    bound_default_daily_limit: int,
) -> str:
    if scope == "bound_default":
        return (
            f"今日默认米米号实时数据查询额度已用完（{limit} 次）。"
            "仍可查看已有缓存；没有缓存的数据请明天再试。"
        )
    if scope == "bound_other":
        return (
            f"今日已实时查询过米米号 {player_id} 的这项数据。"
            "仍可查看已有缓存；没有缓存的数据请明天再试。"
        )
    message = (
        f"今日未绑定米米号的实时数据查询额度已用完（{limit} 次）。"
        "仍可查看已有缓存；没有缓存的数据请明天再试。"
    )
    if bound_default_daily_limit <= limit:
        return message
    return (
        f"{message}\n"
        "绑定默认米米号后，查询该米米号实时数据的每日额度可从 "
        f"{limit} 次提升至 {bound_default_daily_limit} 次。\n"
        "首次成功查询时可按提示设为默认米米号。"
    )
