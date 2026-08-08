# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Literal, Protocol

from ironsbot.core.time import TZ_CN
from ironsbot.services.seer.external_references import (
    SeerInfoReference,
    SeerInfoReferences,
)

if TYPE_CHECKING:
    from collections.abc import Callable

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
        qq_user_id: int,
        scope: PlayerQueryQuotaScope,
        player_id: int,
        action_key: str,
        limit: int,
    ) -> PlayerQueryUsage: ...

    def record(  # noqa: PLR0913
        self,
        *,
        local_date: date,
        qq_user_id: int,
        scope: PlayerQueryQuotaScope,
        player_id: int,
        action_key: str,
        amount: int,
    ) -> PlayerQueryUsage: ...


class SuperuserLookup(Protocol):
    def is_superuser(self, user_id: int) -> bool: ...


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
    """Persistent daily budgets for foreground logical server work."""

    def __init__(  # noqa: PLR0913 - composed persistence and reference services
        self,
        config: PlayerQueryLimitsConfig,
        bindings: PlayerBindingStore,
        features: SuperuserLookup,
        store: PlayerQueryLimitStore,
        *,
        external_references: SeerInfoReferences | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._bindings = bindings
        self._features = features
        self._store = store
        self._external_references = external_references
        self._now = now or _now_cn

    def check(
        self,
        *,
        qq_user_id: int,
        player_id: int,
        action_key: str,
    ) -> PlayerQueryQuotaDecision:
        if not self._config.enabled:
            return PlayerQueryQuotaDecision(allowed=True)
        if (
            self._config.superuser_bypass
            and self._features.is_superuser(qq_user_id)
        ):
            return PlayerQueryQuotaDecision(allowed=True)

        scope, storage_player_id, storage_action_key, limit = self._quota_key(
            qq_user_id=qq_user_id,
            player_id=player_id,
            action_key=action_key,
        )
        usage = self._store.status(
            local_date=self._now().date(),
            qq_user_id=qq_user_id,
            scope=scope,
            player_id=storage_player_id,
            action_key=storage_action_key,
            limit=limit,
        )
        if usage.allowed:
            return PlayerQueryQuotaDecision(allowed=True)
        return PlayerQueryQuotaDecision(
            allowed=False,
            message=self._quota_exhausted_message(
                scope=scope,
                player_id=player_id,
                limit=usage.limit,
                bound_default_daily_limit=(
                    self._config.bound_default_daily_limit
                ),
            ),
        )

    def record_successful_work(
        self,
        *,
        qq_user_id: int,
        player_id: int,
        action_key: str,
        units: frozenset[str],
    ) -> PlayerQueryQuotaDecision:
        if not units:
            return PlayerQueryQuotaDecision(allowed=True)
        if not self._config.enabled:
            return PlayerQueryQuotaDecision(allowed=True)
        if (
            self._config.superuser_bypass
            and self._features.is_superuser(qq_user_id)
        ):
            return PlayerQueryQuotaDecision(allowed=True)

        scope, storage_player_id, storage_action_key, _limit = self._quota_key(
            qq_user_id=qq_user_id,
            player_id=player_id,
            action_key=action_key,
        )
        self._store.record(
            local_date=self._now().date(),
            qq_user_id=qq_user_id,
            scope=scope,
            player_id=storage_player_id,
            action_key=storage_action_key,
            amount=len(units),
        )
        return PlayerQueryQuotaDecision(allowed=True)

    def check_general_query(
        self,
        *,
        qq_user_id: int,
        action_key: str,
    ) -> PlayerQueryQuotaDecision:
        return self.check(
            qq_user_id=qq_user_id,
            player_id=self._bound_player_id(qq_user_id),
            action_key=action_key,
        )

    def record_general_work(
        self,
        *,
        qq_user_id: int,
        action_key: str,
        units: frozenset[str],
    ) -> PlayerQueryQuotaDecision:
        return self.record_successful_work(
            qq_user_id=qq_user_id,
            player_id=self._bound_player_id(qq_user_id),
            action_key=action_key,
            units=units,
        )

    def consume(
        self,
        *,
        qq_user_id: int,
        player_id: int,
        action_key: str,
    ) -> PlayerQueryQuotaDecision:
        """Compatibility helper for one logical work unit.

        Production query paths use ``record_successful_work`` after OneBot
        delivery succeeds. Keeping this small wrapper makes existing callers
        and older integrations explicit rather than silently changing their
        accounting semantics.
        """

        return self.record_successful_work(
            qq_user_id=qq_user_id,
            player_id=player_id,
            action_key=action_key,
            units=frozenset((action_key,)),
        )

    def _quota_key(
        self,
        *,
        qq_user_id: int,
        player_id: int,
        action_key: str,
    ) -> tuple[PlayerQueryQuotaScope, int, str, int]:
        del action_key
        binding = self._bindings.get(qq_user_id)
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
            0,
            "all",
            int(
                getattr(
                    self._config,
                    "bound_other_daily_limit",
                    getattr(self._config, "other_target_action_daily_limit", 0),
                )
            ),
        )

    def _bound_player_id(self, qq_user_id: int) -> int:
        return int(self._bindings.get(qq_user_id).player_id or 0)

    def _quota_exhausted_message(
        self,
        *,
        scope: PlayerQueryQuotaScope,
        player_id: int,
        limit: int,
        bound_default_daily_limit: int,
    ) -> str:
        message = _quota_exhausted_message(
            scope=scope,
            player_id=player_id,
            limit=limit,
            bound_default_daily_limit=bound_default_daily_limit,
        )
        if self._external_references is None:
            return message
        return self._external_references.append(
            message,
            SeerInfoReference.PLAYER_QUERY,
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
    del player_id
    if scope == "bound_default":
        return (
            f"今日默认米米号的查询额度已用完（{limit} 项）。"
            "仍可查看已有缓存；没有缓存的数据请明天再试。"
        )
    if scope == "bound_other":
        return (
            f"今日查询其他米米号的额度已用完（{limit} 项）。"
            "仍可查看已有缓存；没有缓存的数据请明天再试。"
        )
    message = (
        f"今日未绑定米米号的查询额度已用完（{limit} 项）。"
        "仍可查看已有缓存；没有缓存的数据请明天再试。"
    )
    if bound_default_daily_limit <= limit:
        return message
    return (
        f"{message}\n"
        "绑定默认米米号后，查询该米米号的每日查询额度可从 "
        f"{limit} 项提升至 {bound_default_daily_limit} 项。\n"
        "额度按成功获取的数据项目结算；缓存、预热和超时不计入。\n"
        "首次成功查询时可按提示设为默认米米号。"
    )
