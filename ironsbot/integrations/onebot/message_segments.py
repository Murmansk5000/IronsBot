# SPDX-License-Identifier: MIT
"""OneBot wire segments and the facts required for own-account echo checks."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, TypeAlias

from typing_extensions import TypedDict

from ironsbot.core.own_commands import OwnAccountInput
from ironsbot.core.platform import ConversationRef, Platform

if TYPE_CHECKING:
    from collections.abc import Sequence


class OneBotSegment(TypedDict):
    type: str
    data: dict[str, Any]


OneBotMessage: TypeAlias = list[OneBotSegment]

# OneBot v11 CQ grammar; arrays already contain literal, unescaped data.
_CQ_SEGMENT = re.compile(
    r"\[CQ:(?P<type>[a-zA-Z0-9-_.]+)"
    r"(?P<params>(?:,[a-zA-Z0-9-_.]+=[^,\]]*)*),?\]"
)


class OneBotMessageDecodeError(ValueError):
    def __init__(self) -> None:
        super().__init__("Invalid OneBot message segments")


def decode_onebot_segments(value: object) -> OneBotMessage:
    if isinstance(value, str):
        return _decode_cq(value)
    if not isinstance(value, list):
        raise OneBotMessageDecodeError
    result: OneBotMessage = []
    for segment in value:
        if not isinstance(segment, dict):
            raise OneBotMessageDecodeError
        kind = segment.get("type")
        data = segment.get("data")
        if (
            not isinstance(kind, str)
            or not kind
            or (data is not None and not isinstance(data, dict))
        ):
            raise OneBotMessageDecodeError
        data = {} if data is None else dict(data)
        if kind == "text" and not isinstance(data.get("text"), str):
            raise OneBotMessageDecodeError
        result.append({"type": kind, "data": data})
    return result


def _unescape_cq(value: str) -> str:
    return (
        value.replace("&#44;", ",")
        .replace("&#91;", "[")
        .replace("&#93;", "]")
        .replace("&amp;", "&")
    )


def _decode_cq(value: str) -> OneBotMessage:
    result: OneBotMessage = []
    position = 0
    for match in _CQ_SEGMENT.finditer(value):
        if match.start() > position:
            result.append(
                {
                    "type": "text",
                    "data": {"text": _unescape_cq(value[position : match.start()])},
                }
            )
        kind, params = match.group("type"), match.group("params").lstrip(",")
        if kind == "text":
            if params:
                result.append({"type": "text", "data": {"text": _unescape_cq(params)}})
        else:
            result.append(
                {
                    "type": kind,
                    "data": {
                        key: _unescape_cq(item)
                        for key, item in (
                            param.split("=", 1) for param in params.split(",") if param
                        )
                    },
                }
            )
        position = match.end()
    if position < len(value):
        result.append(
            {"type": "text", "data": {"text": _unescape_cq(value[position:])}}
        )
    return result


def onebot_message_text(message: Sequence[OneBotSegment]) -> str:
    return "".join(
        str(segment["data"].get("text", ""))
        for segment in message
        if segment["type"] == "text"
    )


def encode_onebot_message(message: Sequence[OneBotSegment]) -> str:
    """Format protocol diagnostics without depending on native message objects."""

    def escape(value: str, *, comma: bool = True) -> str:
        escaped = (
            value.replace("&", "&amp;").replace("[", "&#91;").replace("]", "&#93;")
        )
        return escaped.replace(",", "&#44;") if comma else escaped

    parts: list[str] = []
    for segment in message:
        if segment["type"] == "text":
            parts.append(escape(segment["data"]["text"], comma=False))
        else:
            params = ",".join(
                f"{key}={escape(str(value))}"
                for key, value in segment["data"].items()
                if value is not None
            )
            suffix = f",{params}" if params else ""
            parts.append(f"[CQ:{segment['type']}{suffix}]")
    return "".join(parts)


def onebot_own_account_input(
    account_id: str,
    conversation: ConversationRef,
    message: Sequence[OneBotSegment],
    *,
    is_own_message: bool,
) -> OwnAccountInput | None:
    if conversation.platform is not Platform.ONEBOT or conversation.kind != "group":
        return None
    return OwnAccountInput(
        account_id,
        conversation,
        is_own_message,
        onebot_message_text(message),
        tuple(
            str(segment["data"].get("qq", ""))
            for segment in message
            if segment["type"] == "at"
        ),
        any(segment["type"] not in {"text", "reply", "at"} for segment in message),
    )
