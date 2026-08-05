# SPDX-License-Identifier: MIT
"""OneBot poke-hint contracts consumed by the OneBot help plugin."""

from __future__ import annotations

from typing import Protocol


class OneBotPokeEvent(Protocol):
    """Small event view sufficient to decide whether the bot was poked."""

    self_id: int
    target_id: int


class OneBotHelpHintPort(Protocol):
    """OneBot-only hint policy exposed to the passive poke matcher."""

    def get_poke_reply(
        self,
        *,
        group_id: int | None,
        user_id: int,
    ) -> str | None: ...

    def get_default_poke_hint(
        self,
        *,
        group_id: int | None,
        user_id: int,
        group_role: str | None = None,
    ) -> str | None: ...

    def can_send(self, group_id: int | None, *, now: float | None = None) -> bool: ...


def is_onebot_poke_at_bot(event: OneBotPokeEvent) -> bool:
    """Return whether one OneBot poke event explicitly targets this bot."""
    return event.target_id == event.self_id
