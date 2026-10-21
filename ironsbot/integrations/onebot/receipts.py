# SPDX-License-Identifier: MIT
"""Validate protocol receipts before reporting a send as delivered."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ironsbot.core.outbound import DeliveryFailureKind, SendResult
from ironsbot.integrations.onebot.message_rendering import (
    OneBotOutboundMessageError,
    parse_reply_message_id,
)

if TYPE_CHECKING:
    from ironsbot.core.outbound import ExecutionIdentity


@dataclass(frozen=True, slots=True)
class OneBotSendFailure:
    result: SendResult
    interrupted: bool = False


def onebot_send_failure(
    error: Exception, *, execution_identity: ExecutionIdentity | None = None
) -> OneBotSendFailure:
    text = " ".join((type(error).__name__, str(error), repr(error))).casefold()
    offline = any(
        marker in text for marker in ("1006514", "账号状态为离线", "账号已离线")
    )
    interrupted = (
        offline
        or isinstance(error, ConnectionError)
        or any(
            marker in text
            for marker in (
                "connection closed",
                "connection reset",
                "websocket is closed",
                "网络连接异常",
            )
        )
    )
    return OneBotSendFailure(
        SendResult(
            delivered=False,
            error_code="delivery_failed",
            error_message=type(error).__name__,
            failure_kind=DeliveryFailureKind.TRANSPORT_UNAVAILABLE
            if offline
            else DeliveryFailureKind.UNCERTAIN,
            execution_identity=execution_identity,
        ),
        interrupted,
    )


def onebot_result_message_id(result: object) -> str | None:
    if isinstance(result, dict):
        value: Any = result.get("message_id")
    else:
        value = getattr(result, "message_id", None)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        return str(parse_reply_message_id(str(value)))
    except OneBotOutboundMessageError:
        return None


def onebot_send_result(
    result: object, *, execution_identity: ExecutionIdentity | None = None
) -> SendResult:
    message_id = onebot_result_message_id(result)
    if message_id is None:
        return SendResult(
            delivered=False,
            error_code="missing_message_id",
            error_message="Send response omitted a valid message_id",
            failure_kind=DeliveryFailureKind.UNCERTAIN,
            execution_identity=execution_identity,
        )
    return SendResult(
        delivered=True, message_id=message_id, execution_identity=execution_identity
    )
