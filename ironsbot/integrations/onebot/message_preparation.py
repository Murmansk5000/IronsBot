# SPDX-License-Identifier: MIT
# Copyright (c) 2021 NoneBot
# Protocol behavior adapted from https://github.com/nonebot/adapter-onebot.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""Prepare OneBot addressing and reply metadata without framework events."""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.integrations.onebot.message_envelope import OneBotReplyEnvelope

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ironsbot.integrations.onebot.connections import OneBotConnection
    from ironsbot.integrations.onebot.message_segments import (
        OneBotMessage,
        OneBotSegment,
    )

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PreparedOneBotMessage:
    message: OneBotMessage
    addressed_to_bot: bool
    reply: OneBotReplyEnvelope | None


def _trim_at(message: OneBotMessage, index: int) -> None:
    if len(message) > index and message[index]["type"] == "text":
        text = message[index]["data"]["text"].lstrip()
        if text:
            message[index]["data"]["text"] = text
        else:
            del message[index]


def _ensure_content(message: OneBotMessage) -> None:
    if not message:
        message.append({"type": "text", "data": {"text": ""}})


async def _prepare_reply(
    connection: OneBotConnection,
    message: OneBotMessage,
    reply: OneBotReplyEnvelope | None,
    *,
    addressed: bool,
) -> tuple[OneBotReplyEnvelope | None, bool]:
    index = next((i for i, part in enumerate(message) if part["type"] == "reply"), None)
    if index is None:
        return reply, addressed
    try:
        result = await connection.call_api(
            "get_msg", message_id=int(message[index]["data"]["id"])
        )
        reply = OneBotReplyEnvelope.model_validate(result)
    except Exception as error:  # noqa: BLE001 - optional protocol metadata, never log bodies
        logger.warning(
            "OneBot reply metadata unavailable: error_type=%s", type(error).__name__
        )
        return reply, addressed
    sender = reply.sender.user_id
    if sender is not None:
        addressed = addressed or str(sender) == str(connection.self_id)
        del message[index]
        if (
            len(message) > index
            and message[index]["type"] == "at"
            and message[index]["data"].get("qq") == str(sender)
        ):
            del message[index]
    _trim_at(message, index)
    _ensure_content(message)
    return reply, addressed


def _prepare_addressing(
    message: OneBotMessage, account_id: str, *, private: bool, addressed: bool
) -> bool:
    _ensure_content(message)
    if private:
        return True

    def is_bot(part: OneBotSegment) -> bool:
        return part["type"] == "at" and str(part["data"].get("qq", "")) == account_id

    if is_bot(message[0]):
        addressed = True
        # Preserve the installed adapter's two-leading-mention normalization.
        for _ in range(2):
            if not message or not is_bot(message[0]):
                break
            del message[0]
            _trim_at(message, 0)
    if not addressed:
        index = len(message) - 1
        if (
            message[index]["type"] == "text"
            and not message[index]["data"]["text"].strip()
            and index > 0
        ):
            index -= 1
        if is_bot(message[index]):
            addressed = True
            del message[index:]
    _ensure_content(message)
    return addressed


async def prepare_onebot_message(  # noqa: PLR0913 - protocol facts, not business policy
    connection: OneBotConnection,
    message: OneBotMessage,
    *,
    private: bool,
    addressed_to_bot: bool = False,
    reply: OneBotReplyEnvelope | None = None,
    nicknames: Iterable[str] = (),
) -> PreparedOneBotMessage:
    prepared: OneBotMessage = []
    for part in deepcopy(message):
        if part["type"] == "text" and prepared and prepared[-1]["type"] == "text":
            prepared[-1]["data"]["text"] += part["data"]["text"]
        else:
            prepared.append(part)
    reply, addressed = await _prepare_reply(
        connection, prepared, reply, addressed=addressed_to_bot
    )
    addressed = _prepare_addressing(
        prepared, str(connection.self_id), private=private, addressed=addressed
    )
    names = {re.escape(name) for name in nicknames}
    if prepared[0]["type"] == "text" and names:
        pattern = "|".join(names)
        text = prepared[0]["data"]["text"]
        if match := re.search(rf"^({pattern})([\s,，]*|$)", text, re.IGNORECASE):
            addressed = True
            prepared[0]["data"]["text"] = text[match.end() :]
    return PreparedOneBotMessage(prepared, addressed, reply)
