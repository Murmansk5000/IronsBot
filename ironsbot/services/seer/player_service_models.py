# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncio

    from ironsbot.services.seer.player_binding import PlayerBindingState
    from ironsbot.services.seer.player_query import PlayerQuerySectionPlan
    from ironsbot.services.seer.player_shortcuts import PlayerShortcutKind
    from ironsbot.services.seer.query_result import QueryReply


@dataclass(frozen=True, slots=True)
class PlayerBaseSnapshot:
    """Fields confirmed by one base-player query and reusable in its menu."""

    player_id: int
    user_info: Any
    more_info: Any
    online_info: Any | None
    team_name: str

    @property
    def nick(self) -> str:
        return str(getattr(self.user_info, "nick", ""))


@dataclass(slots=True)
class PendingPlayerQuery:
    player_id: int
    user_info: Any
    more_info: Any
    player_message: str
    section_plan: PlayerQuerySectionPlan
    quota_recorded: bool = False
    base_snapshot: PlayerBaseSnapshot | None = None


@dataclass(frozen=True, slots=True)
class PlayerQueryResult:
    pending: PendingPlayerQuery | None = None
    message: str = ""
    offer_binding: bool = False
    binding_replacement: PlayerBindingState | None = None


@dataclass(frozen=True, slots=True)
class _CachedDetailReply:
    expires_at: float
    reply: QueryReply


@dataclass(slots=True)
class _BackgroundRefresh:
    replies: dict[PlayerShortcutKind, asyncio.Future[QueryReply | None]]
    started_at: float
    task: asyncio.Task[None] | None = None
    base_snapshot: PlayerBaseSnapshot | None = None
