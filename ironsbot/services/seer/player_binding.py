# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, NamedTuple, Protocol

from ironsbot.core.time import TZ_CN

if TYPE_CHECKING:
    from ironsbot.core.platform import ActorRef


class PlayerBindingState(NamedTuple):
    actor: ActorRef
    player_id: int | None = None
    player_nick: str = ""
    choice_completed: bool = False
    last_changed_at: datetime | None = None
    last_bound_player_id: int | None = None

    @property
    def is_bound(self) -> bool:
        return self.player_id is not None


class PlayerBindingStore(Protocol):
    def get(self, actor: ActorRef) -> PlayerBindingState: ...

    def bind(  # noqa: PLR0913 - atomic binding policy inputs
        self,
        *,
        actor: ActorRef,
        player_id: int,
        player_nick: str,
        changed_at: datetime | None = None,
        cooldown_days: int = 0,
        only_if_unbound: bool = False,
        reset_cooldown: bool = False,
    ) -> None: ...

    def decline(self, *, actor: ActorRef) -> None: ...

    def unbind(
        self,
        *,
        actor: ActorRef,
        changed_at: datetime | None = None,
    ) -> bool: ...


class PlayerBindingError(ValueError):
    """A binding changed or its cooldown was active inside the write transaction."""


def binding_change_error(
    binding: PlayerBindingState,
    *,
    target_player_id: int,
    now: datetime,
    cooldown_days: int,
) -> str:
    last_player = binding.last_bound_player_id or binding.player_id
    if last_player is None or last_player == target_player_id:
        return ""
    changed_at = binding.last_changed_at
    if changed_at is None or cooldown_days <= 0:
        return ""
    available_date = china_time(changed_at).date() + timedelta(days=cooldown_days)
    if china_time(now).date() >= available_date:
        return ""
    current = (
        f"当前默认米米号：{binding.player_id}。"
        if binding.player_id is not None
        else "当前未绑定米米号。"
    )
    return (
        f"换绑未成功。{current}"
        f"请于 {available_date.strftime('%Y年%m月%d日')} 00:00 起再试。"
    )


def china_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(TZ_CN)
