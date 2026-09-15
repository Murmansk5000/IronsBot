from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.outbound import OutboundMessage, SendResult
from ironsbot.services.portable_reply import (
    PortableReply,
    deliver_portable_reply,
    progress_operation_reply,
)

if TYPE_CHECKING:
    from ironsbot.services.portable_reply import ProgressReporter


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_at", [0, 1, 2, 3])
@pytest.mark.parametrize("failure", ["rejected", "exception", "cancelled"])
async def test_ordered_delivery_aborts_on_every_interrupted_stage(
    failure_at: int,
    failure: str,
) -> None:
    messages = tuple(
        OutboundMessage.from_text(text) for text in ("one", "two", "three")
    )
    sent: list[OutboundMessage] = []
    acknowledged, aborted, observer = Mock(), Mock(), Mock()
    follow_up = AsyncMock(return_value=messages[2])

    async def send(message: OutboundMessage) -> SendResult:
        sent.append(message)
        if len(sent) - 1 == failure_at:
            if failure == "exception":
                raise OSError
            if failure == "cancelled":
                raise asyncio.CancelledError
            return SendResult(delivered=False, error_code="rejected")
        return SendResult(delivered=True, message_id="sent")

    reply = PortableReply(
        messages[0],
        additional_messages=(messages[1],),
        on_delivered=acknowledged,
        on_delivery_failed=aborted,
        follow_up=follow_up,
    )
    if failure_at < len(messages) and failure != "rejected":
        expected = OSError if failure == "exception" else asyncio.CancelledError
        with pytest.raises(expected):
            await deliver_portable_reply(reply, send, on_sent=observer)
    else:
        assert await deliver_portable_reply(reply, send, on_sent=observer) is (
            failure_at == len(messages)
        )
    assert sent == list(messages[: failure_at + 1])
    assert acknowledged.call_count == int(failure_at > 0)
    assert aborted.call_count == int(failure_at < len(messages))
    assert follow_up.await_count == int(failure_at >= len(messages) - 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("present_error", [False, True])
async def test_follow_up_error_policy_is_explicit(*, present_error: bool) -> None:
    aborted = Mock()
    send = AsyncMock(return_value=SendResult(delivered=True, message_id="sent"))
    error = ValueError("domain error")
    reply = PortableReply(
        OutboundMessage.from_text("initial"),
        on_delivery_failed=aborted,
        follow_up=AsyncMock(side_effect=error),
    )
    display = Mock(return_value=OutboundMessage.from_text("unavailable"))
    if present_error:
        assert await deliver_portable_reply(reply, send, on_follow_up_error=display)
        display.assert_called_once_with(error)
        aborted.assert_not_called()
        assert send.await_count == len(("initial", "error"))
    else:
        with pytest.raises(ValueError, match="domain error"):
            await deliver_portable_reply(reply, send)
        aborted.assert_called_once_with()
        send.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancellation_before_first_progress_joins_owned_operation() -> None:
    started, stopped = asyncio.Event(), asyncio.Event()

    async def operation(_report: ProgressReporter) -> str:
        try:
            started.set()
            await asyncio.Event().wait()
            return "not reached"
        finally:
            stopped.set()

    pending = asyncio.create_task(progress_operation_reply(operation))
    await asyncio.wait_for(started.wait(), timeout=1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert stopped.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_at", [0, 1])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_interrupted_delivery_releases_progress_operation(
    failure_at: int,
    *,
    cancelled: bool,
) -> None:
    stopped = asyncio.Event()

    async def operation(report: ProgressReporter) -> str:
        try:
            await report("initial")
            await asyncio.Event().wait()
            return "not reached"
        finally:
            stopped.set()

    reply = replace(
        await progress_operation_reply(operation),
        additional_messages=(OutboundMessage.from_text("additional"),),
    )
    count = 0

    async def send(_message: OutboundMessage) -> SendResult:
        nonlocal count
        current = count
        count += 1
        if current == failure_at:
            if cancelled:
                raise asyncio.CancelledError
            return SendResult(delivered=False, error_code="rejected")
        return SendResult(delivered=True, message_id="sent")

    if cancelled:
        with pytest.raises(asyncio.CancelledError):
            await deliver_portable_reply(reply, send)
    else:
        assert not await deliver_portable_reply(reply, send)
    await asyncio.wait_for(stopped.wait(), timeout=1)
