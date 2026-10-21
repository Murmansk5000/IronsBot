# SPDX-License-Identifier: MIT
"""Normalized own-account command facts, without transport event objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.core.platform import ConversationRef


@dataclass(frozen=True, slots=True)
class OwnAccountInput:
    account_id: str
    conversation: ConversationRef
    is_own_message: bool
    text: str
    mentioned_ids: tuple[str, ...] = ()
    has_other_segments: bool = False


@dataclass(frozen=True, slots=True)
class OwnAccountCommand:
    text: str
    admin_binding: bool = False
