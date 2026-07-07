# SPDX-License-Identifier: MIT
from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Message

RED_PACKET_SEGMENT_TYPES = frozenset(
    {
        "redbag",
        "redpacket",
        "red_packet",
        "hongbao",
        "lucky_money",
    }
)
RED_PACKET_RAW_MARKERS = (
    "[CQ:redbag",
    "[CQ:redpacket",
    "[CQ:red_packet",
    "[CQ:hongbao",
    "[redbag:",
    "[redpacket:",
    "[red_packet:",
    "[hongbao:",
    "[QQ红包]",
    "QQ红包",
)
RED_PACKET_NOTICE_MARKERS = (*RED_PACKET_RAW_MARKERS, "红包")


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


def is_red_packet_message(message: Message) -> bool:
    for segment in message:
        if segment.type.lower() in RED_PACKET_SEGMENT_TYPES:
            return True
        if _segment_payload_contains_red_packet_marker(segment.data.values()):
            return True

    raw_message = str(message)
    return any(marker in raw_message for marker in RED_PACKET_RAW_MARKERS)


def is_red_packet_payload(payload: Mapping[str, Any]) -> bool:
    return _payload_contains_marker(payload, markers=RED_PACKET_NOTICE_MARKERS)


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


def summarize_red_packet_message(message: Message) -> str:
    for segment in message:
        if segment.type.lower() in RED_PACKET_SEGMENT_TYPES:
            title = str(segment.data.get("title") or "").strip()
            if title:
                return title[:80]
            return "红包消息"

    plaintext = message.extract_plain_text().strip()
    if plaintext:
        return plaintext[:80]

    raw_message = str(message).strip()
    return raw_message[:80]


def _segment_payload_contains_red_packet_marker(values: Iterable[Any]) -> bool:
    for value in values:
        if not isinstance(value, str):
            continue
        if any(marker in value for marker in RED_PACKET_RAW_MARKERS):
            return True
    return False


def _payload_contains_marker(value: Any, *, markers: tuple[str, ...]) -> bool:
    if isinstance(value, str):
        return any(marker in value for marker in markers)
    if isinstance(value, Mapping):
        return any(
            _payload_contains_marker(item, markers=markers)
            for item in value.values()
        )
    if isinstance(value, Iterable):
        return any(_payload_contains_marker(item, markers=markers) for item in value)
    return False


__all__ = [
    "RedPacketNoticeLimiter",
    "build_red_packet_notice_message",
    "is_red_packet_message",
    "is_red_packet_payload",
    "summarize_red_packet_message",
]
