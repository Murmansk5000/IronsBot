from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.integrations.qq_official.reply_transport import QQOfficialReplyTransport
from ironsbot.services.portable_reply import deliver_portable_reply

if TYPE_CHECKING:
    from ironsbot.core.outbound import OutboundMessenger
    from ironsbot.core.platform import IncomingMessageRef
    from ironsbot.services.portable_reply import PortableReply


async def deliver_reply(
    messenger: OutboundMessenger, incoming: IncomingMessageRef, reply: PortableReply
) -> None:
    transport = QQOfficialReplyTransport(messenger, incoming)
    await deliver_portable_reply(
        reply, transport.send, on_sent=transport.record_receipt
    )
