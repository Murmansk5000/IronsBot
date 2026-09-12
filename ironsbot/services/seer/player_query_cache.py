# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass, replace
from time import monotonic

from ironsbot.core.time import now, remaining_observation_ttl
from ironsbot.services.seer.player_service_models import (
    PendingPlayerQuery,
    PlayerQueryResult,
)


@dataclass(frozen=True, slots=True)
class _CachedPlayerQuery:
    expires_at: float
    pending: PendingPlayerQuery


class PlayerQueryCache:
    """Short-lived complete player replies used only as live-query fallback."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl_seconds = ttl_seconds
        self._items: dict[int, _CachedPlayerQuery] = {}

    @classmethod
    def from_config(cls, config: object) -> PlayerQueryCache:
        player_config = getattr(config, "player", None)
        refresh_config = getattr(player_config, "background_refresh", None)
        return cls(float(getattr(refresh_config, "cache_ttl_seconds", 300.0)))

    def result(
        self,
        player_id: int,
        *,
        offer_binding: bool,
    ) -> PlayerQueryResult | None:
        cached = self._items.get(player_id)
        if cached is None:
            return None
        if cached.expires_at <= monotonic() or self._remaining(cached.pending) <= 0:
            self._items.pop(player_id, None)
            return None
        return PlayerQueryResult(
            pending=replace(cached.pending, quota_recorded=True),
            offer_binding=offer_binding,
        )

    def put(self, pending: PendingPlayerQuery) -> None:
        remaining = self._remaining(pending)
        if remaining <= 0:
            return
        self._items[pending.player_id] = _CachedPlayerQuery(
            expires_at=monotonic() + remaining,
            pending=replace(pending, quota_recorded=False),
        )

    def _remaining(self, pending: PendingPlayerQuery) -> float:
        snapshot = pending.base_snapshot
        if snapshot is None or snapshot.player_id != pending.player_id:
            return 0.0
        return remaining_observation_ttl(
            snapshot.fetched_at, self._ttl_seconds, at=now().timestamp()
        )
