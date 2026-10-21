# SPDX-License-Identifier: MIT
"""QQ Official reply templates, protocol sends and receipt diagnostics."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.outbound import COMMAND_REPLY_TEMPLATE
from ironsbot.core.platform import reference_digest

if TYPE_CHECKING:
    from ironsbot.core.outbound import OutboundMessage, OutboundMessenger, SendResult
    from ironsbot.core.platform import IncomingMessageRef
    from ironsbot.services.portable_reply import DeliveryStage

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QQOfficialReplyTransport:
    messenger: OutboundMessenger
    incoming: IncomingMessageRef
    account_label: str = "official-account"

    async def send(self, message: OutboundMessage) -> SendResult:
        prepared = COMMAND_REPLY_TEMPLATE.prepare(self.incoming, message)
        if prepared.context is not None:
            return await self.messenger.reply(prepared.context, prepared.message)
        return await self.messenger.send(self.incoming.conversation, prepared.message)

    def record_receipt(self, stage: DeliveryStage, result: SendResult) -> None:
        if result.delivered:
            logger.info(
                "QQ Official reply delivered: stage=%s account=%s kind=%s",
                stage,
                self.account_label,
                self.incoming.conversation.kind,
            )
        else:
            logger.warning(
                "QQ Official reply failed: stage=%s account=%s kind=%s ref=%s "
                "code=%s failure_kind=%s trace_id=%s",
                stage,
                self.account_label,
                self.incoming.conversation.kind,
                reference_digest(self.incoming.conversation.id),
                result.error_code,
                result.failure_kind.value if result.failure_kind is not None else None,
                result.trace_id,
            )
