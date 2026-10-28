# SPDX-License-Identifier: MIT
"""Preparation failures cannot have submitted a chat message."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, TypeVar

from ironsbot.core.outbound import DeliveryFailureKind, SendResult
from ironsbot.services.bilibili.delivery_lifecycle import STAGE_DEADLINE_SECONDS
from ironsbot.services.bilibili.media_preparation import MediaPreparationError
from ironsbot.services.messaging.image_collage import ImageCollageError

_T = TypeVar("_T")


async def bounded_preparation(operation: Awaitable[_T]) -> _T:
    return await asyncio.wait_for(operation, timeout=STAGE_DEADLINE_SECONDS)


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.core.outbound import OutboundMessage
    from ironsbot.services.bilibili.delivery_ledger import DynamicDeliveryLedger


def preparation_failure(error: Exception) -> SendResult:
    chain = []
    current: BaseException = error
    while current not in chain:
        chain.append(current)
        if current.__cause__ is None:
            break
        current = current.__cause__
    retryable = not isinstance(error, MediaPreparationError) and any(
        isinstance(cause, (TimeoutError, ConnectionError))
        or (isinstance(cause, ImageCollageError) and cause.retryable)
        for cause in chain
    )
    return SendResult(
        delivered=False,
        error_code=f"media_prepare:{type(error).__name__}",
        failure_kind=DeliveryFailureKind.RETRYABLE
        if retryable
        else DeliveryFailureKind.PERMANENT,
    )


async def prepare_frozen_text(
    ledger: DynamicDeliveryLedger | None,
    dynamic_id: str,
    prepare: Callable[[], Awaitable[OutboundMessage | None]],
) -> OutboundMessage | None:
    if ledger is not None:
        found, message = ledger.load_text(dynamic_id)
        if found:
            return message
    message = await prepare()
    return ledger.freeze_text(dynamic_id, message) if ledger else message
