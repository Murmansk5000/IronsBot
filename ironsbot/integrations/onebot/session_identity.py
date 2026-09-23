# SPDX-License-Identifier: MIT
"""Interaction ownership must include the receiving OneBot account."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nonebot.adapters import Event


def event_session_key(event: Event) -> str:
    return f"bot:{getattr(event, 'self_id', '')}:{event.get_session_id()}"
