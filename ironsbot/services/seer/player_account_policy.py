# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from ironsbot.core.time import TZ_CN

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.config.models.seer import SeerConfig
    from ironsbot.services.seer.player_binding import PlayerBindingStore
    from ironsbot.services.seer.player_query_limits import PlayerQueryQuotaService
    from ironsbot.services.seer.player_service_models import PendingPlayerQuery

logger = logging.getLogger(__name__)


class PlayerAccountPolicyMixin:
    """Binding cooldown and per-user query quota behavior."""

    _config: SeerConfig
    _bindings: PlayerBindingStore
    _quotas: PlayerQueryQuotaService | None
    _now: Callable[[], datetime]

    def _save_binding(
        self,
        qq_user_id: int,
        pending: PendingPlayerQuery,
    ) -> str:
        change_error = self._binding_change_error(
            qq_user_id,
            target_player_id=pending.player_id,
        )
        if change_error:
            return change_error
        try:
            self._bindings.bind(
                qq_user_id=qq_user_id,
                player_id=pending.player_id,
                player_nick=str(pending.user_info.nick),
                changed_at=self._now(),
            )
        except Exception as error:
            logger.exception("保存米米号绑定失败")
            return f"⚠️ 默认米米号设置保存失败：{error}"
        return f"已设置默认米米号：{pending.player_id}。"

    def _check_quota(
        self,
        *,
        qq_user_id: int,
        player_id: int,
        action_key: str,
    ) -> str:
        if self._quotas is None:
            return ""
        decision = self._quotas.check(
            qq_user_id=qq_user_id,
            player_id=player_id,
            action_key=action_key,
        )
        return "" if decision.allowed else decision.message

    def _record_quota(
        self,
        *,
        qq_user_id: int,
        player_id: int,
        action_key: str,
    ) -> str:
        if self._quotas is None:
            return ""
        decision = self._quotas.consume(
            qq_user_id=qq_user_id,
            player_id=player_id,
            action_key=action_key,
        )
        return "" if decision.allowed else decision.message

    def _record_successful_quota(
        self,
        *,
        qq_user_id: int,
        player_id: int,
        action_key: str,
    ) -> None:
        quota_message = self._record_quota(
            qq_user_id=qq_user_id,
            player_id=player_id,
            action_key=action_key,
        )
        if quota_message:
            logger.warning(
                "player query quota changed before successful record: "
                "user=%s player=%s action=%s",
                qq_user_id,
                player_id,
                action_key,
            )

    def _binding_change_error(
        self,
        qq_user_id: int,
        *,
        target_player_id: int | None = None,
    ) -> str:
        binding = self._bindings.get(qq_user_id)
        if target_player_id is not None and binding.player_id == target_player_id:
            return ""
        changed_at = binding.last_changed_at
        cooldown_days = self._config.player.binding.change_cooldown_days
        if changed_at is None or cooldown_days <= 0:
            return ""
        available_date = _china_time(changed_at).date() + timedelta(days=cooldown_days)
        if _china_time(self._now()).date() >= available_date:
            return ""
        return (
            "默认米米号最近刚更改，"
            f"请于 {available_date.strftime('%Y年%m月%d日')} 00:00 起再试。"
        )


def _china_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(TZ_CN)
