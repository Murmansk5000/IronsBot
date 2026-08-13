# SPDX-License-Identifier: MIT
"""OneBot reply metadata normalized across adapter variants."""

from __future__ import annotations

from typing import Any


def event_reply_message_id(event: object) -> int | None:
    """Read a reply id from metadata first, then the current reply segment."""

    reply = getattr(event, "reply", None)
    if (message_id := _positive_int(getattr(reply, "message_id", None))) is not None:
        return message_id
    for message in _current_messages(event):
        for segment in message:
            if getattr(segment, "type", "") != "reply":
                continue
            data = getattr(segment, "data", {})
            raw_message_id = getattr(data, "get", lambda _key: None)("id")
            if (message_id := _positive_int(raw_message_id)) is not None:
                return message_id
    return None


def _current_messages(event: object) -> tuple[Any, ...]:
    """Return current segments before adapter-provided original segments.

    NapCat can retain a reply segment in ``message`` while omitting it from
    ``original_message``.  Both describe the incoming event, but the current
    message is the authoritative source for reply routing.
    """

    message = getattr(event, "message", None)
    original_message = getattr(event, "original_message", None)
    return tuple(
        candidate
        for candidate in (message, original_message)
        if candidate is not None
    )


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
