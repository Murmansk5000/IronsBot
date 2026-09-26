# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from ironsbot.core.platform import reference_digest
from ironsbot.core.time import TZ_CN

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.config.models.seer import SeerConfig
    from ironsbot.core.platform import ActorRef
    from ironsbot.services.seer.player_binding import (
        PlayerBindingState,
        PlayerBindingStore,
    )
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
        actor: ActorRef,
        pending: PendingPlayerQuery,
        *,
        bypass_cooldown: bool = False,
    ) -> str:
        current = self._bindings.get(actor)
        if current.player_id == pending.player_id:
            return f"当前已绑定该米米号：{pending.player_id}。"
        change_error = (
            ""
            if bypass_cooldown
            else self._binding_change_error(
                actor,
                target_player_id=pending.player_id,
            )
        )
        if change_error:
            return change_error
        try:
            self._bindings.bind(
                actor=actor,
                player_id=pending.player_id,
                player_nick=str(pending.user_info.nick),
                changed_at=self._now(),
            )
        except Exception as error:
            logger.exception("保存米米号绑定失败")
            return f"⚠️ 默认米米号设置保存失败：{error}"
        return f"已设置默认米米号：{pending.player_id}。"

    def save_binding_choice(
        self,
        actor: ActorRef,
        pending: PendingPlayerQuery,
        *,
        accepted: bool,
        replacing_existing: bool = False,
    ) -> str:
        if accepted:
            current = self._bindings.get(actor)
            if (
                not replacing_existing
                and current.player_id is not None
                and current.player_id != pending.player_id
            ):
                status = (
                    "当前绑定已变化，已保留现有绑定；如需换绑，请重新发送绑定指令。"
                )
            else:
                status = self._save_binding(actor, pending)
        elif replacing_existing:
            status = "已保留当前默认米米号。"
        else:
            try:
                self._bindings.decline(actor=actor)
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
        nick = str(pending.user_info.nick)
        if replacement is not None and replacement.player_id is not None:
            current = str(replacement.player_id)
            if replacement.player_nick.strip():
                current += f"（{replacement.player_nick.strip()}）"
            return (
                f"当前默认米米号：{current}\n"
                f"已查到米米号：{pending.player_id}（{nick}）\n\n"
                "是否将默认米米号改为该账号？\n"
                "回复“是”或“y”确认，回复“否”或“n”保留当前绑定。"
            )
        limits = self._config.player.query_limits
        quota_hint = ""
        if (
            limits.enabled
            and limits.bound_default_daily_limit > limits.unbound_daily_limit
        ):
            quota_hint = (
                "设为默认米米号后，查询该米米号的每日查询额度可从 "
                f"{limits.unbound_daily_limit} 项提升至 "
                f"{limits.bound_default_daily_limit} 项。\n"
                "额度按成功获取的数据项目结算；缓存、预热和超时不计入。\n"
            )
        return (
            f"已查到米米号：{pending.player_id}（{nick}）\n\n"
            "如果这是你自己的米米号，是否将其设为默认米米号？\n"
            "回复“是”或“y”确认，回复“否”或“n”跳过。\n"
            f"{quota_hint}"
            "设置后发送“米米号 / 收集 / 巅峰 / 群星牌”即可快捷查询。\n"
            "以后可发送“解绑米米号”解除绑定。"
        )

    def bind_shortcut_target(self, actor: ActorRef, player_id: int) -> str:
        """Confirm a resolved numeric target without fetching profile for its name."""
        current = self._bindings.get(actor)
        if current.player_id is not None:
            return "已保留当前默认米米号。"
        error = self._binding_change_error(actor, target_player_id=player_id)
        if error:
            return error
        self._bindings.bind(
            actor=actor, player_id=player_id, player_nick="", changed_at=self._now()
        )
        return f"已设置默认米米号：{player_id}。"

    def shortcut_binding_offer(self, player_id: int) -> str:
        limits = self._config.player.query_limits
        benefit = (
            f"绑定后每日查询额度：{limits.bound_default_daily_limit} 项"
            f"（未绑定为 {limits.unbound_daily_limit} 项）。\n"
            if limits.enabled
            and limits.bound_default_daily_limit > limits.unbound_daily_limit
            else ""
        )
        return (
            f"查询目标米米号：{player_id}\n"
            "如果这是你自己的米米号，是否设为默认米米号？\n"
            "回复“是/y”绑定后继续，回复“否/n”不绑定并继续；0 退出。\n"
            f"{benefit}缓存、预热和超时不计入实时查询额度。"
        )

    def _check_quota(
        self,
        *,
        actor: ActorRef,
        player_id: int,
        action_key: str,
    ) -> str:
        if self._quotas is None:
            return ""
        decision = self._quotas.check(
            actor=actor,
            player_id=player_id,
            action_key=action_key,
        )
        return "" if decision.allowed else decision.message

    def _record_quota(
        self,
        *,
        actor: ActorRef,
        player_id: int,
        action_key: str,
    ) -> str:
        if self._quotas is None:
            return ""
        decision = self._quotas.consume(
            actor=actor,
            player_id=player_id,
            action_key=action_key,
        )
        return "" if decision.allowed else decision.message

    def _record_successful_quota(
        self,
        *,
        actor: ActorRef,
        player_id: int,
        action_key: str,
    ) -> None:
        quota_message = self._record_quota(
            actor=actor,
            player_id=player_id,
            action_key=action_key,
        )
        if quota_message:
            logger.warning(
                "player query quota changed before successful record: "
                "user=%s player=%s action=%s",
                reference_digest(actor.id),
                player_id,
                action_key,
            )

    def _binding_change_error(
        self,
        actor: ActorRef,
        *,
        target_player_id: int | None = None,
    ) -> str:
        binding = self._bindings.get(actor)
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
