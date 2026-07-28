# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.services.seer.player_request_protection import (
    PlayerRequestBusyError,
    PlayerRequestPausedError,
    PlayerRequestReconnectError,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.player_query import PlayerQuerySectionPlan
    from ironsbot.services.seer.player_shortcuts import PlayerShortcutKind


PLAYER_REQUEST_ERRORS = (
    PlayerRequestBusyError,
    PlayerRequestPausedError,
    PlayerRequestReconnectError,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def background_refresh_kinds(
    plan: PlayerQuerySectionPlan,
) -> tuple[PlayerShortcutKind, ...]:
    kinds: list[PlayerShortcutKind] = []
    if plan.has_collection:
        kinds.append("collection")
    if plan.needs_peak_section:
        kinds.append("peak")
    if plan.has_autocard_rank:
        kinds.append("autocard")
    return tuple(kinds)


def shortcut_operation_label(kind: PlayerShortcutKind) -> str:
    return {
        "collection": "收集查询",
        "peak": "巅峰查询",
        "autocard": "群星牌查询",
    }[kind]
