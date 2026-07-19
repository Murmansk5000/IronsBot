# SPDX-License-Identifier: MIT
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(slots=True)
class RedPacketNoticeLimiter:
    cooldown_seconds: float
    _last_sent_by_group: dict[int, float] = field(default_factory=dict)

    def can_send(self, group_id: int, *, now: float | None = None) -> bool:
        if self.cooldown_seconds <= 0:
            return True

        current_time = time.monotonic() if now is None else now
        last_sent = self._last_sent_by_group.get(group_id)
        if last_sent is not None and current_time - last_sent < self.cooldown_seconds:
            return False

        self._last_sent_by_group[group_id] = current_time
        return True


def build_red_packet_notice_message(
    *,
    group_id: int,
    group_name: str = "",
    sender_id: int,
    summary: str = "",
) -> str:
    group_label = f"{group_name}（{group_id}）" if group_name else str(group_id)
    lines = [
        "🧧 检测到群红包",
        f"群：{group_label}",
        f"发送者：{sender_id}",
    ]
    if summary:
        lines.append(f"内容：{summary}")
    return "\n".join(lines)
