# SPDX-License-Identifier: MIT
"""Shared typed port for resolving a player reference within a conversation."""

from __future__ import annotations

from collections.abc import Callable

from ironsbot.core.platform import ConversationRef

PlayerReferenceLookup = Callable[[str, ConversationRef], int | None]
