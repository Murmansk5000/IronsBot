# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Protocol


class PokeLikeEvent(Protocol):
    self_id: int
    target_id: int


def is_poke_at_bot(event: PokeLikeEvent) -> bool:
    return event.target_id == event.self_id


__all__ = ["is_poke_at_bot"]
