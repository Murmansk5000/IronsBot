# SPDX-License-Identifier: MIT
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.core.platform import ActorRef, ConversationRef


@dataclass(slots=True)
class RedPacketNoticeLimiter:
    cooldown_seconds: float
    _last_sent_by_conversation: dict[ConversationRef, float] = field(
        default_factory=dict,
    )

    def can_send(
        self,
        conversation: ConversationRef,
        *,
        now: float | None = None,
    ) -> bool:
        if self.cooldown_seconds <= 0:
            return True

        current_time = time.monotonic() if now is None else now
        last_sent = self._last_sent_by_conversation.get(conversation)
        if last_sent is not None and current_time - last_sent < self.cooldown_seconds:
            return False

        self._last_sent_by_conversation[conversation] = current_time
        return True


def build_red_packet_notice_message(
    *,
    conversation: ConversationRef,
    conversation_name: str = "",
    sender: ActorRef,
    summary: str = "",
) -> str:
    group_label = (
        f"{conversation_name}（{conversation.id}）"
        if conversation_name
        else conversation.id
    )
    lines = [
        "🧧 检测到群红包",
        f"群：{group_label}",
        f"发送者：{sender.id}",
    ]
    if summary:
        lines.append(f"内容：{summary}")
    return "\n".join(lines)
