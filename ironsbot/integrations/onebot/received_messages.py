# SPDX-License-Identifier: MIT
"""OneBot received and sent messages share admission without native events."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any

from ironsbot.core.command_catalog import command_context_from_input
from ironsbot.integrations.onebot.ingress_facts import (
    OneBotMessageOrigin,
    onebot_admission_input,
)
from ironsbot.integrations.onebot.message_envelope import decode_received_message
from ironsbot.integrations.onebot.message_facts import OneBotMessageFacts
from ironsbot.integrations.onebot.message_preparation import (
    PreparedOneBotMessage,
    prepare_onebot_message,
)
from ironsbot.integrations.onebot.message_segments import onebot_message_text
from ironsbot.integrations.onebot.red_packet import (
    is_red_packet_message,
    red_packet_group_name,
    summarize_red_packet_message,
)

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.integrations.onebot.connections import OneBotConnection
    from ironsbot.integrations.onebot.message_envelope import (
        OneBotMessageEnvelope,
        OneBotSentMessageEnvelope,
    )
    from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
    from ironsbot.services.messaging.red_packet import RedPacketNoticeService
    from ironsbot.services.onebot_admission import (
        OneBotAdmissionInput,
        OneBotAdmissionService,
    )
    from ironsbot.services.portable_commands import PortableCommandRouter

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OneBotReceivedMessages:
    admission: OneBotAdmissionService
    router: PortableCommandRouter
    messenger: OneBotOutboundMessenger
    nicknames: frozenset[str] = frozenset()
    red_packets: RedPacketNoticeService | None = None

    async def handle(
        self, connection: OneBotConnection, payload: dict[str, Any]
    ) -> None:
        envelope = decode_received_message(payload)
        if envelope is None:
            return
        if str(envelope.self_id) != str(connection.self_id):
            logger.warning("OneBot message rejected: receiving account mismatch")
            return
        if envelope.post_type == "message_sent" and envelope.message_type == "private":
            return
        incoming, prepared = await self._admission_input(connection, envelope)
        decision = await self.admission.decide(incoming)
        context = decision.context
        if decision.rejection is not None or context is None:
            return
        if (
            envelope.post_type == "message_sent"
            and envelope.user_id != envelope.self_id
        ):
            return
        group_id = envelope.group_id if envelope.message_type == "group" else None
        packet_summary = (
            summarize_red_packet_message(prepared.message)
            if self.red_packets is not None
            and group_id is not None
            and is_red_packet_message(prepared.message)
            else None
        )
        claimed = await self.router.ingress.handle(
            context, partial(self.messenger.reply_from, connection, context)
        )
        if not claimed and packet_summary is not None:
            assert group_id is not None
            await self._red_packet(connection, context, group_id, packet_summary)

    async def _admission_input(
        self,
        connection: OneBotConnection,
        envelope: OneBotMessageEnvelope | OneBotSentMessageEnvelope,
    ) -> tuple[OneBotAdmissionInput, PreparedOneBotMessage]:
        sent = envelope.post_type == "message_sent"
        if sent and envelope.user_id != envelope.self_id:
            prepared = PreparedOneBotMessage(
                envelope.message, addressed_to_bot=False, reply=envelope.reply
            )
        else:
            prepared = await prepare_onebot_message(
                connection,
                envelope.message,
                private=envelope.message_type == "private",
                addressed_to_bot=envelope.to_me,
                reply=envelope.reply,
                nicknames=self.nicknames,
            )
        group_id = envelope.group_id if envelope.message_type == "group" else None
        reply = prepared.reply
        sender = envelope.sender
        facts = OneBotMessageFacts(
            account_id=str(envelope.self_id),
            user_id=str(envelope.user_id),
            message_id=str(envelope.message_id),
            text=onebot_message_text(prepared.message),
            segments=tuple(prepared.message),
            original_segments=tuple(envelope.message),
            group_id=str(group_id) if group_id is not None else None,
            group_role=sender.role
            if group_id is not None and sender is not None
            else None,
            reply_to_id=str(reply.message_id) if reply is not None else None,
            reply_sender_id=(
                str(reply.sender.user_id)
                if reply is not None and reply.sender.user_id is not None
                else None
            ),
            raw_message=envelope.raw_message,
            addressed_to_bot=group_id is not None and prepared.addressed_to_bot,
            actor_display_name=(sender.nickname or sender.card or "")
            if sender is not None
            else "",
        )
        incoming = onebot_admission_input(
            facts,
            OneBotMessageOrigin.SENT_GROUP
            if sent
            else OneBotMessageOrigin.GROUP
            if group_id is not None
            else OneBotMessageOrigin.PRIVATE,
        )
        return incoming, prepared

    async def _red_packet(
        self,
        connection: OneBotConnection,
        context: MessageInputContext,
        group_id: int,
        summary: str,
    ) -> None:
        assert self.red_packets is not None
        try:
            await self.red_packets.handle(
                command_context_from_input(context),
                summary=summary,
                conversation_name=partial(red_packet_group_name, connection, group_id),
            )
        except Exception as error:  # noqa: BLE001 - same shared management error boundary
            await self.admission.errors.report(context, error)
