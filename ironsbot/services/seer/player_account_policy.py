# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ironsbot.core.platform import reference_digest
from ironsbot.services.seer.player_binding import (
    BindingResult,
    PlayerBindingError,
    binding_available_date,
    binding_change_error,
    binding_cooldown_hint,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

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
        only_if_unbound: bool = False,
        expected_binding: PlayerBindingState | None = None,
    ) -> BindingResult:
        current = self._bindings.get(actor)
        if current.player_id == pending.player_id and not bypass_cooldown:
            return BindingResult(succeeded=True)
        change_error = (
            ""
            if bypass_cooldown
            else self._binding_change_error(
                actor,
                target_player_id=pending.player_id,
            )
        )
        if change_error:
            return BindingResult(succeeded=False, message=change_error)
        try:
            self._bindings.bind(
                actor=actor,
                player_id=pending.player_id,
                player_nick=str(pending.user_info.nick),
                changed_at=self._now(),
                cooldown_days=(
                    0
                    if bypass_cooldown
                    else self._config.player.binding.change_cooldown_days
                ),
                only_if_unbound=only_if_unbound,
                reset_cooldown=bypass_cooldown,
                expected_binding=expected_binding,
            )
        except PlayerBindingError as error:
            return BindingResult(succeeded=False, message=str(error))
        except Exception:
            logger.exception("保存米米号绑定失败")
            return BindingResult(
                succeeded=False, message="⚠️ 默认米米号设置保存失败，请稍后重试。"
            )
        return BindingResult(
            succeeded=True,
            message=f"已设置默认米米号：{pending.player_id}。",
            changed=True,
        )

    def save_binding_choice(
        self,
        actor: ActorRef,
        pending: PendingPlayerQuery,
        *,
        accepted: bool,
        replacing_existing: bool = False,
        expected_binding: PlayerBindingState | None = None,
    ) -> BindingResult:
        if accepted:
            current = self._bindings.get(actor)
            if (
                not replacing_existing
                and current.player_id is not None
                and current.player_id != pending.player_id
            ):
                return BindingResult(
                    succeeded=False,
                    message="当前绑定已变化，已保留现有绑定；如需换绑，请重新发送绑定指令。",
                )
            return self._save_binding(
                actor,
                pending,
                only_if_unbound=not replacing_existing,
                expected_binding=expected_binding,
            )
        if replacing_existing:
            return BindingResult(succeeded=True, message="已保留当前默认米米号。")
        try:
            self._bindings.decline(actor=actor)
            return BindingResult(succeeded=True)
        except Exception:
            logger.exception("保存米米号绑定选择失败")
            return BindingResult(
                succeeded=False, message="⚠️ 默认米米号设置保存失败，请稍后重试。"
            )

    def binding_state(self, actor: ActorRef) -> PlayerBindingState:
        return self._bindings.get(actor)

    def binding_success_notice(self, actor: ActorRef) -> str:
        binding = self._bindings.get(actor)
        days = self._config.player.binding.change_cooldown_days
        text = f"已设置默认米米号：{binding.player_id}。\n"
        if days <= 0:
            return text + "解除绑定：解绑米米号。"
        unbind = "解除绑定：解绑米米号（解绑不重置冷却）。"
        if binding.last_changed_at is None:
            return text + unbind
        available = binding_available_date(
            binding.last_changed_at, days, date_format="%Y-%m-%d"
        )
        return f"{text}可再次换绑时间：{available}。\n{unbind}"

    def binding_offer(
        self,
        pending: PendingPlayerQuery,
        *,
        actor: ActorRef,
    ) -> str:
        return self._binding_confirmation(pending.player_id, actor=actor)

    def _binding_confirmation(self, player_id: int, *, actor: ActorRef) -> str:
        hint = binding_cooldown_hint(
            self._bindings.get(actor),
            player_id,
            now=self._now(),
            cooldown_days=self._config.player.binding.change_cooldown_days,
        )
        limits = self._config.player.query_limits
        lines = [f"是否绑定米米号：{player_id}？", "建议绑定本人使用的米米号。"]
        if (
            limits.enabled
            and limits.bound_default_daily_limit > limits.unbound_daily_limit
        ):
            lines.append(
                f"绑定后每日额度：{limits.unbound_daily_limit} → "
                f"{limits.bound_default_daily_limit} 项。"
            )
        lines.extend(
            ("绑定后可直接发送：米米号 / 收集 / 巅峰 / 群星牌等快捷口令。", "")
        )
        if hint:
            lines.append(hint)
        lines.append("回复 是/y 绑定，否/n 不绑定，0 退出。")
        return "\n".join(lines)

    def bind_shortcut_target(
        self,
        actor: ActorRef,
        player_id: int,
        *,
        expected_binding: PlayerBindingState | None = None,
    ) -> BindingResult:
        """Confirm a resolved numeric target without fetching profile for its name."""
        current = self._bindings.get(actor)
        if current.player_id is not None:
            return BindingResult(
                succeeded=current.player_id == player_id,
                message="当前绑定状态已变化，请重新发送查询指令。",
            )
        error = self._binding_change_error(actor, target_player_id=player_id)
        if error:
            return BindingResult(succeeded=False, message=error)
        try:
            self._bindings.bind(
                actor=actor,
                player_id=player_id,
                player_nick="",
                changed_at=self._now(),
                cooldown_days=self._config.player.binding.change_cooldown_days,
                only_if_unbound=True,
                expected_binding=expected_binding,
            )
        except PlayerBindingError as error:
            return BindingResult(succeeded=False, message=str(error))
        except Exception:
            logger.exception("保存快捷查询绑定失败")
            return BindingResult(
                succeeded=False, message="⚠️ 默认米米号设置保存失败，请稍后重试。"
            )
        return BindingResult(succeeded=True, changed=True)

    def shortcut_binding_offer(self, player_id: int, *, actor: ActorRef) -> str:
        return self._binding_confirmation(player_id, actor=actor)

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
        return binding_change_error(
            binding,
            target_player_id=target_player_id if target_player_id is not None else -1,
            now=self._now(),
            cooldown_days=self._config.player.binding.change_cooldown_days,
        )
