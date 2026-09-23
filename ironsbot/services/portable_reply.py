# SPDX-License-Identifier: MIT
"""Delivery-aware values shared by portable command runtimes."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from ironsbot.core.outbound import OutboundMessage, SendResult

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.seer.data_queries import DataQueryImageReply

PortableFollowUp = Callable[[], Awaitable[OutboundMessage]]
ProgressReporter = Callable[[str], Awaitable[None]]
ProgressOperation = Callable[
    [ProgressReporter],
    Awaitable[OutboundMessage | str],
]
DeliveryStage = Literal["initial", "additional", "follow_up"]


@dataclass(frozen=True, slots=True)
class PortableReply:
    """One prepared reply with work committed only after transport success."""

    message: OutboundMessage
    additional_messages: tuple[OutboundMessage, ...] = ()
    on_delivered: Callable[[], None] | None = None
    on_delivery_failed: Callable[[], None] | None = None
    follow_up: PortableFollowUp | None = None
    on_finished: Callable[[], None] | None = None
    is_current: Callable[[], bool] | None = None

    def delivered(self) -> None:
        if self.on_delivered is not None:
            self.on_delivered()

    def delivery_failed(self) -> None:
        if self.on_delivery_failed is not None:
            self.on_delivery_failed()


async def deliver_portable_reply(
    reply: PortableReply,
    send: Callable[[OutboundMessage], Awaitable[SendResult]],
    *,
    on_sent: Callable[[DeliveryStage, SendResult], None] | None = None,
    on_follow_up_error: Callable[[Exception], OutboundMessage] | None = None,
) -> bool:
    """Own ordered delivery and abort unfinished work on every interrupted path."""

    async def transmit(message: OutboundMessage, stage: DeliveryStage) -> bool:
        return await _transmit_reply(reply, send, message, stage, on_sent)

    completed = False
    try:
        if not await transmit(reply.message, "initial"):
            return False
        reply.delivered()
        for message in reply.additional_messages:
            if not await transmit(message, "additional"):
                return False
        if reply.follow_up is not None:
            if reply.is_current is not None and not reply.is_current():
                return False
            message = await _follow_up_message(reply.follow_up, on_follow_up_error)
            completed = await transmit(message, "follow_up")
        else:
            completed = True
        return completed
    finally:
        try:
            if not completed:
                reply.delivery_failed()
        finally:
            if reply.on_finished is not None:
                reply.on_finished()


async def _transmit_reply(
    reply: PortableReply,
    send: Callable[[OutboundMessage], Awaitable[SendResult]],
    message: OutboundMessage,
    stage: DeliveryStage,
    on_sent: Callable[[DeliveryStage, SendResult], None] | None,
) -> bool:
    if reply.is_current is not None and not reply.is_current():
        return False
    receipt = await send(message)
    if on_sent is not None:
        on_sent(stage, receipt)
    return receipt.delivered


async def _follow_up_message(
    follow_up: PortableFollowUp,
    on_error: Callable[[Exception], OutboundMessage] | None,
) -> OutboundMessage:
    try:
        return await follow_up()
    except Exception as error:
        if on_error is None:
            raise
        return on_error(error)


async def progress_operation_reply(
    operation: ProgressOperation,
) -> PortableReply:
    """Pause progress-driven work until its first message is delivered."""

    loop = asyncio.get_running_loop()
    first_progress: asyncio.Future[OutboundMessage] = loop.create_future()
    delivery_gate = asyncio.Event()

    async def report(message: str) -> None:
        if first_progress.done():
            return
        first_progress.set_result(OutboundMessage.from_text(message))
        await delivery_gate.wait()

    task = asyncio.ensure_future(operation(report))
    try:
        done, _pending = await asyncio.wait(
            (task, first_progress),
            return_when=asyncio.FIRST_COMPLETED,
        )
    except BaseException:
        task.cancel()
        first_progress.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
    if task in done:
        if not first_progress.done():
            first_progress.cancel()
        return PortableReply(_outbound(await task))

    def release() -> None:
        delivery_gate.set()

    def cancel() -> None:
        task.cancel()
        delivery_gate.set()

    async def finish() -> OutboundMessage:
        return _outbound(await task)

    return PortableReply(
        first_progress.result(),
        on_delivered=release,
        on_delivery_failed=cancel,
        follow_up=finish,
    )


def _outbound(message: OutboundMessage | str) -> OutboundMessage:
    if isinstance(message, str):
        return OutboundMessage.from_text(message)
    return message


class PortableOperation(Protocol):
    def __call__(
        self,
        text: str,
        context: MessageInputContext,
    ) -> Awaitable[
        PortableReply | OutboundMessage | str | DataQueryImageReply | None
    ]: ...
