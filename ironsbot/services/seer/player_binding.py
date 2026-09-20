# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, Protocol

if TYPE_CHECKING:
    from datetime import datetime

    from ironsbot.core.platform import ActorRef


class PlayerBindingState(NamedTuple):
    actor: ActorRef
    player_id: int | None = None
    player_nick: str = ""
    choice_completed: bool = False
    last_changed_at: datetime | None = None

    @property
    def is_bound(self) -> bool:
        return self.player_id is not None


class PlayerBindingStore(Protocol):
    def get(self, actor: ActorRef) -> PlayerBindingState: ...

    def bind(
        self,
        *,
        actor: ActorRef,
        player_id: int,
        player_nick: str,
        changed_at: datetime | None = None,
    ) -> None: ...

    def decline(self, *, actor: ActorRef) -> None: ...

    def unbind(
        self,
        *,
        actor: ActorRef,
        changed_at: datetime | None = None,
    ) -> bool: ...
