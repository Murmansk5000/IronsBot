# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from ironsbot.core.time import TZ_CN
from ironsbot.services.seer.player_binding import (
    player_binding_offer_message,
    player_binding_replacement_offer_message,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.config.models.seer import SeerConfig
    from ironsbot.services.seer.player_binding import (
        PlayerBindingState,
        PlayerBindingStore,
    )
    from ironsbot.services.seer.player_query_limits import PlayerQueryQuotaService
    from ironsbot.services.seer.player_service_models import PendingPlayerQuery
    from ironsbot.services.seer.query_result import QueryReply

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
        current = self._bindings.get(qq_user_id)
        if current.player_id == pending.player_id:
            return f"当前已绑定该米米号：{pending.player_id}。"
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

    def _save_binding_without_cooldown(
        self,
        qq_user_id: int,
        pending: PendingPlayerQuery,
    ) -> str:
        try:
            self._bindings.bind_without_cooldown(
                qq_user_id=qq_user_id,
                player_id=pending.player_id,
                player_nick=str(pending.user_info.nick),
            )
        except Exception as error:
            logger.exception("保存无冷却米米号绑定失败")
            return f"⚠️ 默认米米号设置保存失败：{error}"
        return f"已设置默认米米号：{pending.player_id}。"

    def save_binding_choice(
        self,
        qq_user_id: int,
        pending: PendingPlayerQuery,
        *,
        accepted: bool,
        replacing_existing: bool = False,
    ) -> str:
        if accepted:
            status = self._save_binding(qq_user_id, pending)
        elif replacing_existing:
            status = "已保留当前默认米米号。"
        else:
            try:
                self._bindings.decline(qq_user_id=qq_user_id)
                status = "已跳过默认米米号设置。"
            except Exception as error:
                logger.exception("保存米米号绑定选择失败")
                status = f"⚠️ 默认米米号设置保存失败：{error}"
        pending.player_message = f"{status}\n\n{pending.player_message}"
        return status

    def binding_offer(
        self,
        pending: PendingPlayerQuery,
        *,
        replacement: PlayerBindingState | None = None,
    ) -> str:
        if replacement is not None and replacement.player_id is not None:
            return player_binding_replacement_offer_message(
                replacement.player_id,
                replacement.player_nick,
                pending.player_id,
                str(pending.user_info.nick),
            )
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
        decision = self._quotas.record_successful_work(
            qq_user_id=qq_user_id,
            player_id=player_id,
            action_key=action_key,
            units=frozenset((action_key,)),
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

    def _settle_query_work(
        self,
        *,
        qq_user_id: int,
        player_id: int,
        action_key: str,
        units: frozenset[str],
    ) -> None:
        if self._quotas is None or not units:
            return
        decision = self._quotas.record_successful_work(
            qq_user_id=qq_user_id,
            player_id=player_id,
            action_key=action_key,
            units=units,
        )
        if not decision.allowed:
            logger.warning(
                "player query quota settlement changed unexpectedly: "
                "user=%s player=%s action=%s",
                qq_user_id,
                player_id,
                action_key,
            )

    def record_returned_detail_reply(
        self,
        *,
        qq_user_id: int,
        player_id: int,
        action_key: str,
        reply: QueryReply,
    ) -> None:
        work = reply.query_work
        if work is None:
            return
        self._settle_query_work(
            qq_user_id=qq_user_id,
            player_id=player_id,
            action_key=action_key,
            units=work.billable_units,
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
