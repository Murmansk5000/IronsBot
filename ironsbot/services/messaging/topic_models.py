# SPDX-License-Identifier: MIT
"""Typed topic registry and delivery records shared by storage and runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ironsbot.core.platform import ConversationRef


@dataclass(frozen=True, slots=True)
class PushTopic:
    key: str
    name: str
    enabled: bool = True
    code_registered: bool = False


TopicDeliveryStatus = Literal["pending", "delivered", "failed", "uncertain", "skipped"]


@dataclass(frozen=True, slots=True)
class TopicDeliveryRecord:
    topic: str
    conversation: ConversationRef
    status: TopicDeliveryStatus
    created_at: float


def topic_subscription_key(key: str) -> str:
    return f"push_topic:{key}"
