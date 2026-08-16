# SPDX-License-Identifier: GPL-3.0-or-later
"""Superuser-only player-binding workflow."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.player_service_models import PlayerQueryResult

if TYPE_CHECKING:
    from ironsbot.services.seer.player_service import PlayerService


async def bind_player_for_user(
    player: PlayerService,
    player_id: int,
    *,
    actor_qq_user_id: int,
    target_qq_user_id: int,
    group_id: int | None = None,
) -> PlayerQueryResult:
    """Set another user's binding without imposing a change cooldown."""

    result = await player.query(
        player_id,
        qq_user_id=actor_qq_user_id,
        explicit=True,
        group_id=group_id,
    )
    if result.message or result.pending is None:
        return result

    pending = result.pending
    status = player._save_binding_without_cooldown(target_qq_user_id, pending)
    if status.startswith("⚠️"):
        return PlayerQueryResult(message=status)
    pending.player_message = (
        f"已为该成员{status.removeprefix('已')}\n\n{pending.player_message}"
    )
    return PlayerQueryResult(pending=pending)
