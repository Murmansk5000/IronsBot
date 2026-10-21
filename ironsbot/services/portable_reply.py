# SPDX-License-Identifier: MIT
"""Delivery-aware values shared by portable command runtimes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AsyncExitStack, aclosing, contextmanager
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal, Protocol

from ironsbot.core.message_origin import current_message_origin, message_origin
from ironsbot.core.outbound import OutboundMessage, SendResult
from ironsbot.core.semantic_requests import (
    current_semantic_request_trace,
    semantic_request_trace_scope,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.semantic_requests import SemanticRequestTrace
    from ironsbot.services.seer.data_queries import DataQueryImageReply

PortableFollowUp = Callable[[], Awaitable[OutboundMessage]]
PortableMessageStream = Callable[[], AsyncGenerator[OutboundMessage, None]]
PortableErrorReply = Callable[[Exception], Awaitable[OutboundMessage]]
ProgressReporter = Callable[[str], Awaitable[None]]
ProgressOperation = Callable[
    [ProgressReporter],
    Awaitable[OutboundMessage | str],
]
DeliveryStage = Literal["initial", "additional", "follow_up"]


@dataclass(slots=True)
class RequestOutcome:
    failed: bool = False


@dataclass(frozen=True, slots=True)
class PortableReply:
    """One prepared reply with work committed only after transport success."""

    message: OutboundMessage
    additional_messages: tuple[OutboundMessage, ...] = ()
    additional_stream: PortableMessageStream | None = None
    on_delivered: Callable[[], None] | None = None
    on_delivery_failed: Callable[[], None] | None = None
    follow_up: PortableFollowUp | None = None
    on_finished: Callable[[], None] | None = None
    is_current: Callable[[], bool] | None = None
    continuation: Callable[[], Awaitable[PortableReply | None]] | None = None
    initial_is_advisory: bool = False
    outcome: RequestOutcome = field(default_factory=RequestOutcome, compare=False)
    on_operation_error: PortableErrorReply | None = None
    origin: MessageInputContext | None = field(
        default_factory=current_message_origin, compare=False, repr=False
    )
    semantic_trace: SemanticRequestTrace | None = field(
        default_factory=current_semantic_request_trace, compare=False, repr=False
    )

    @contextmanager
    def execution_scope(self) -> Iterator[None]:
        with (
            message_origin(self.origin),
            semantic_request_trace_scope(self.semantic_trace),
        ):
            yield

    def delivered(self) -> None:
        with self.execution_scope():
            if self.on_delivered is not None:
                self.on_delivered()

    def delivery_failed(self) -> None:
        with self.execution_scope():
            self.outcome.failed = True
            if self.on_delivery_failed is not None:
                self.on_delivery_failed()

    def finished(self) -> None:
        with self.execution_scope():
            try:
                if self.on_finished is not None:
                    self.on_finished()
            except BaseException:
                self.outcome.failed = True
                raise


async def deliver_portable_reply(
    reply: PortableReply,
    send: Callable[[OutboundMessage], Awaitable[SendResult]],
    *,
    on_sent: Callable[[DeliveryStage, SendResult], None] | None = None,
) -> bool:
    """Own ordered delivery and abort unfinished work on every interrupted path."""

    with reply.execution_scope():

        async def transmit(message: OutboundMessage, stage: DeliveryStage) -> bool:
            return await _transmit_reply(reply, send, message, stage, on_sent)

        completed = False
        try:
            initial_sent = await transmit(reply.message, "initial")
            if not initial_sent and not reply.initial_is_advisory:
                return False
            if initial_sent:
                reply.delivered()
            if not await _transmit_additional(reply, transmit):
                return False
            if reply.continuation is not None:
                next_reply = await _continue_reply(reply)
                completed = next_reply is None or await deliver_portable_reply(
                    next_reply,
                    send,
                    on_sent=on_sent,
                )
                reply.outcome.failed |= (
                    next_reply is not None and next_reply.outcome.failed
                )
                return completed
            if reply.follow_up is not None:
                if reply.is_current is not None and not reply.is_current():
                    return False
                message = await _follow_up_message(
                    reply.follow_up, reply.on_operation_error
                )
                completed = await transmit(message, "follow_up")
            else:
                completed = True
            return completed
        finally:
            try:
                if not completed:
                    reply.delivery_failed()
            finally:
                reply.finished()


async def _transmit_additional(
    reply: PortableReply,
    transmit: Callable[[OutboundMessage, DeliveryStage], Awaitable[bool]],
) -> bool:
    for message in reply.additional_messages:
        if not await transmit(message, "additional"):
            return False
    if reply.additional_stream is not None:
        async with aclosing(_stream_messages(reply)) as messages:
            while True:
                if reply.is_current is not None and not reply.is_current():
                    return False
                try:
                    message = await anext(messages)
                except StopAsyncIteration:
                    break
                if not await transmit(message, "additional") or reply.outcome.failed:
                    return False
    return True


async def _transmit_reply(
    reply: PortableReply,
    send: Callable[[OutboundMessage], Awaitable[SendResult]],
    message: OutboundMessage,
    stage: DeliveryStage,
    on_sent: Callable[[DeliveryStage, SendResult], None] | None,
) -> bool:
    if not message.request_succeeded:
        reply.outcome.failed = True
    if reply.is_current is not None and not reply.is_current():
        return False
    try:
        receipt = await send(message)
    except Exception:
        if stage != "initial" or not reply.initial_is_advisory:
            raise
        logging.getLogger(__name__).exception("Slow-query notice delivery failed")
        return False
    if on_sent is not None:
        on_sent(stage, receipt)
    return receipt.delivered


async def _follow_up_message(
    follow_up: PortableFollowUp,
    on_error: PortableErrorReply | None,
) -> OutboundMessage:
    try:
        return await follow_up()
    except Exception as error:
        if on_error is None:
            raise
        return replace(await on_error(error), request_succeeded=False)


async def _continue_reply(reply: PortableReply) -> PortableReply | None:
    assert reply.continuation is not None
    try:
        result = await reply.continuation()
    except Exception as error:
        if reply.on_operation_error is None:
            raise
        result = PortableReply(
            replace(await reply.on_operation_error(error), request_succeeded=False)
        )
    return (
        replace(result, on_operation_error=reply.on_operation_error)
        if result is not None and reply.on_operation_error is not None
        else result
    )


async def _stream_messages(
    reply: PortableReply,
) -> AsyncGenerator[OutboundMessage, None]:
    assert reply.additional_stream is not None
    async with AsyncExitStack() as cleanup:
        try:
            stream = reply.additional_stream()
            cleanup.push_async_callback(stream.aclose)
            async for message in stream:
                yield message
        except Exception as error:
            if reply.on_operation_error is None:
                raise
            yield replace(
                await reply.on_operation_error(error), request_succeeded=False
            )


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


async def slow_operation_reply(
    operation: Awaitable[OutboundMessage | str],
    *,
    delay_seconds: float = 3.0,
) -> PortableReply:
    """Send at most one advisory notice while keeping the actual query alive."""
    from ironsbot.services.operations.request_feedback import request_is_acknowledged

    task = asyncio.ensure_future(operation)
    if request_is_acknowledged():
        return PortableReply(_outbound(await task))
    try:
        done, _ = await asyncio.wait((task,), timeout=delay_seconds)
    except BaseException:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
    if done:
        return PortableReply(_outbound(await task))
    if request_is_acknowledged():
        return PortableReply(_outbound(await task))

    async def finish() -> OutboundMessage:
        return _outbound(await task)

    def cleanup() -> None:
        if not task.done():
            task.cancel()
        elif not task.cancelled():
            task.exception()

    return PortableReply(
        OutboundMessage.from_text("正在查询，完成后发送结果。"),
        follow_up=finish,
        on_finished=cleanup,
        initial_is_advisory=True,
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
