# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, cast

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


def shortcut_timeout_seconds(config: object, kind: PlayerShortcutKind) -> float:
    """Reserve the rank scheduler's bounded budget for peak details."""

    resolved_config = cast("Any", config)
    detail_timeout = float(resolved_config.player.detail_timeout_seconds)
    if kind != "peak":
        return detail_timeout

    rank = getattr(config, "rank", None)
    lookup = getattr(rank, "player_lookup", None)
    total_timeout = getattr(lookup, "total_timeout_seconds", None)
    page_timeout = getattr(lookup, "page_timeout_seconds", None)
    if total_timeout is None or page_timeout is None:
        return detail_timeout
    # Peak base data is collected before the three independently scheduled
    # season boards. Let those boards return their own partial failures.
    return detail_timeout + float(total_timeout) + float(page_timeout)
