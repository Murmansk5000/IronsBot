# SPDX-License-Identifier: MIT
"""OneBot wire segments and the facts required for own-account echo checks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeAlias, TypedDict

from ironsbot.core.own_commands import OwnAccountInput
from ironsbot.core.platform import ConversationRef, Platform

if TYPE_CHECKING:
    from collections.abc import Sequence


class OneBotSegment(TypedDict):
    type: str
    data: dict[str, Any]


OneBotMessage: TypeAlias = list[OneBotSegment]


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
        "".join(
            str(segment["data"].get("text", ""))
            for segment in message
            if segment["type"] == "text"
        ),
        tuple(
            str(segment["data"].get("qq", ""))
            for segment in message
            if segment["type"] == "at"
        ),
        any(segment["type"] not in {"text", "reply", "at"} for segment in message),
    )
