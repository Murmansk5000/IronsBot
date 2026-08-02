# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import Protocol


class PlayerProfileCache(Protocol):
    def registration_time(
        self,
        player_id: int,
        *,
        max_age_days: int = 30,
    ) -> int | None: ...

    def upsert_registration_time(
        self,
        *,
        player_id: int,
        nick: str,
        reg_time: int,
    ) -> None: ...


class NullPlayerProfileCache:
    def registration_time(
        self,
        player_id: int,
        *,
        max_age_days: int = 30,
    ) -> int | None:
        del player_id, max_age_days
        return None

    def upsert_registration_time(
        self,
        *,
        player_id: int,
        nick: str,
        reg_time: int,
    ) -> None:
        del player_id, nick, reg_time
