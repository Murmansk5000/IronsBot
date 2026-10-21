# SPDX-License-Identifier: MIT
"""Shared command delivery, menu receipts and identity observation ownership."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import partial
from typing import TYPE_CHECKING, Literal

from ironsbot.core.outbound import DeliveryFailureKind
from ironsbot.services.portable_reply import deliver_portable_reply

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.outbound import OutboundMessage, SendResult
    from ironsbot.services.command_errors import CommandErrorReporter
    from ironsbot.services.identity_observation import SilentIdentityObservationService
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import DeliveryStage, PortableReply


@dataclass(frozen=True, slots=True)
class CommandReplyDelivery:
    sessions: PortableQuerySessions
    errors: CommandErrorReporter
    identity_observer: SilentIdentityObservationService | None = None

    async def deliver(
        self,
        context: MessageInputContext,
        reply: PortableReply,
        send: Callable[[OutboundMessage], Awaitable[SendResult]],
        *,
        on_sent: Callable[[DeliveryStage, SendResult], None] | None = None,
        purpose: Literal["command", "route_hint"] = "command",
    ) -> bool:
        prepared = replace(
            reply,
            origin=context,
            on_operation_error=partial(self.errors.reply, context),
            on_delivery_error=partial(self.errors.report, context),
        )

        async def observed_send(message: OutboundMessage) -> SendResult:
            observer = self.identity_observer if purpose == "command" else None
            token = (
                observer.record_reply(context.message, message) if observer else None
            )
            result: SendResult | None = None
            try:
                result = await send(message)
                if (
                    not result.delivered
                    and result.attempted
                    and result.failure_kind
                    in {
                        DeliveryFailureKind.UNCERTAIN,
                        DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
                    }
                ):
                    await self.errors.report(
                        context,
                        ConnectionError("Command delivery was not confirmed"),
                        "send",
                    )
                return result
            finally:
                if observer is not None and (result is None or not result.delivered):
                    observer.discard_reply(token)

        def record_receipt(message: OutboundMessage, result: SendResult) -> None:
            self.sessions.record_delivery(context, message, result)

        try:
            return await deliver_portable_reply(
                prepared,
                observed_send,
                on_sent=on_sent,
                on_receipt=record_receipt,
            )
        except Exception:  # noqa: BLE001 - already reported, never log or retry uncertain delivery
            return False
