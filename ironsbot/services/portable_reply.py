# SPDX-License-Identifier: MIT
"""Delivery-aware values shared by portable command runtimes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ironsbot.core.outbound import OutboundMessage, ReplyContext

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.outbound import SendResult
    from ironsbot.core.platform import IncomingMessageRef

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PortableReply:
    """One prepared reply with work committed only after transport success."""

    message: OutboundMessage
    on_delivered: Callable[[], None] | None = None
    on_delivery_failed: Callable[[], None] | None = None
    after_delivered: DeliveryCommit | None = None
    follow_up: PortableFollowUp | None = None

    def delivered(self) -> None:
        if self.on_delivered is not None:
            self.on_delivered()

    def delivery_failed(self) -> None:
        if self.on_delivery_failed is not None:
            self.on_delivery_failed()

    async def commit_delivery(self) -> None:
        """Commit local state and then run any delivery-dependent side effect."""

        self.delivered()
        if self.after_delivered is not None:
            await self.after_delivered()


DeliveryCommit = Callable[[], Awaitable[None]]
PortableFollowUp = Callable[[], Awaitable[PortableReply | OutboundMessage]]
ProgressReporter = Callable[[str], Awaitable[None]]
ProgressOperation = Callable[
    [ProgressReporter],
    Awaitable[PortableReply | OutboundMessage | str],
]


class ReplyMessenger(Protocol):
    """Smallest transport surface required by passive reply delivery."""

    def reply(
        self,
        context: ReplyContext,
        message: OutboundMessage,
    ) -> Awaitable[SendResult]: ...


class ReplySender(Protocol):
    """Send one stage of a passive reply and return its transport receipt."""

    def __call__(self, message: OutboundMessage) -> Awaitable[SendResult]: ...


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
    done, _pending = await asyncio.wait(
        (task, first_progress),
        return_when=asyncio.FIRST_COMPLETED,
    )
    if task in done:
        if not first_progress.done():
            first_progress.cancel()
        return as_portable_reply(await task)

    def release() -> None:
        delivery_gate.set()

    def cancel() -> None:
        task.cancel()
        delivery_gate.set()

    async def finish() -> PortableReply | OutboundMessage:
        result = await task
        return result if isinstance(result, PortableReply) else _outbound(result)

    return PortableReply(
        first_progress.result(),
        on_delivered=release,
        on_delivery_failed=cancel,
        follow_up=finish,
    )


async def deliver_portable_reply(
    messenger: ReplyMessenger,
    incoming: IncomingMessageRef,
    reply: PortableReply,
) -> None:
    """Deliver a portable reply through an outbound messenger."""
    context = ReplyContext.from_message(incoming)

    async def send(message: OutboundMessage) -> SendResult:
        return await messenger.reply(context, message)

    await deliver_reply_stages(send, incoming, reply)


async def deliver_reply_stages(
    send: ReplySender,
    incoming: IncomingMessageRef,
    reply: PortableReply,
) -> None:
    """Commit each reply stage only after its transport receipt succeeds."""

    current = reply
    stage = 0
    while True:
        result = await send(current.message)
        stage_name = "initial" if stage == 0 else f"follow_up_{stage}"
        if not result.delivered:
            current.delivery_failed()
            _log_delivery_failure(incoming, result, stage=stage_name)
            return
        try:
            await current.commit_delivery()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Portable delivery commit failed: platform=%s account=%s kind=%s id=%s",
                incoming.platform.value,
                incoming.conversation.account_id,
                incoming.conversation.kind,
                incoming.conversation.id,
            )
            return
        if current.follow_up is None:
            return
        try:
            follow_up = await current.follow_up()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.exception(
                "Portable deferred operation failed: platform=%s account=%s "
                "kind=%s id=%s",
                incoming.platform.value,
                incoming.conversation.account_id,
                incoming.conversation.kind,
                incoming.conversation.id,
            )
            follow_up = OutboundMessage.from_text(
                f"❌ 操作执行失败：{type(error).__name__}"
            )
        current = (
            follow_up
            if isinstance(follow_up, PortableReply)
            else PortableReply(follow_up)
        )
        stage += 1


def _log_delivery_failure(
    incoming: IncomingMessageRef,
    result: SendResult,
    *,
    stage: str,
) -> None:
    logger.warning(
        "Portable reply failed: platform=%s stage=%s account=%s kind=%s id=%s "
        "code=%s message=%s trace_id=%s",
        incoming.platform.value,
        stage,
        incoming.conversation.account_id,
        incoming.conversation.kind,
        incoming.conversation.id,
        result.error_code,
        result.error_message,
        result.trace_id,
    )


def _outbound(message: OutboundMessage | str) -> OutboundMessage:
    if isinstance(message, str):
        return OutboundMessage.from_text(message)
    return message


def as_portable_reply(
    message: PortableReply | OutboundMessage | str,
) -> PortableReply:
    """Normalize a portable operation result before platform delivery."""

    if isinstance(message, PortableReply):
        return message
    return PortableReply(_outbound(message))


class PortableOperation(Protocol):
    def __call__(
        self,
        text: str,
        context: MessageInputContext,
    ) -> Awaitable[PortableReply | OutboundMessage | str]: ...
