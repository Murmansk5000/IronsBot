# SPDX-License-Identifier: MIT
"""Shared normalized input preparation, command admission and execution."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from ironsbot.core.inbound_claims import InboundMessageKey
from ironsbot.core.platform import Platform
from ironsbot.services.inbound_claims import MemoryInboundMessageClaims
from ironsbot.services.portable_reply import PortableReply
from ironsbot.services.seer.rank_list_parsing import parse_rank_player_target_command

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.core.inbound_claims import InboundMessageClaims
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.outbound import OutboundMessage, SendResult
    from ironsbot.services.command_delivery import CommandReplyDelivery
    from ironsbot.services.identity_observation import SilentIdentityObservationService
    from ironsbot.services.official_union_identity import OfficialUnionIdentityService
    from ironsbot.services.portable_commands import PortableCommandRouter
    from ironsbot.services.portable_reply import DeliveryStage

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CommandIngress:
    router: PortableCommandRouter
    delivery: CommandReplyDelivery
    identity_observer: SilentIdentityObservationService | None = None
    union_identity: OfficialUnionIdentityService | None = None
    claims: InboundMessageClaims = field(default_factory=MemoryInboundMessageClaims)

    async def handle(
        self,
        context: MessageInputContext,
        send: Callable[[OutboundMessage], Awaitable[SendResult]],
        *,
        allows: Callable[[MessageInputContext], bool] | None = None,
        on_sent: Callable[[DeliveryStage, SendResult], None] | None = None,
    ) -> bool:
        """Return whether input was claimed, independently of delivery success."""
        if context.mentions_everyone:
            return False
        if not await self._claim_delivery(context):
            return True
        try:
            context = await self._prepare(context)
            if allows is not None and not allows(context):
                hint = self.router.bare_mention_hint(context)
                if hint is not None:
                    await self.delivery.deliver(
                        context, hint, send, on_sent=on_sent, purpose="route_hint"
                    )
                return hint is not None
            recognized = self.router.recognizes(context)
            logger.info(
                "Command inbound routed: platform=%s account=%s "
                "input_kind=%s recognized=%s",
                context.message.platform.value,
                context.execution_identity.display_name
                if context.execution_identity is not None
                else "unlabelled",
                context.kind.value,
                recognized,
            )
            if not recognized:
                return False
            if (
                self.identity_observer is not None
                and context.message.platform is Platform.QQ_OFFICIAL
                and not context.mentions_bot
            ):
                await self.identity_observer.observe_official_message(
                    context.message, explicitly_addressed=False
                )
        except Exception as error:  # noqa: BLE001 - shared input failure boundary
            reply = PortableReply(await self.delivery.errors.reply(context, error))
            await self.delivery.deliver(context, reply, send, on_sent=on_sent)
            return True
        await self.router.execute(context, send, on_sent=on_sent)
        return True

    async def _claim_delivery(self, context: MessageInputContext) -> bool:
        try:
            return await self.claims.claim(InboundMessageKey.from_context(context))
        except Exception as error:  # noqa: BLE001 - fail closed without replying to arbitrary input
            await self.delivery.errors.report(context, error)
            return False

    async def _prepare(self, context: MessageInputContext) -> MessageInputContext:
        incoming = context.message
        if incoming.platform is not Platform.QQ_OFFICIAL:
            return context
        if self.union_identity is not None:
            await self.union_identity.observe(incoming)
        observer = self.identity_observer
        if (
            observer is None
            or incoming.conversation.kind != "group"
            or not context.mentions_bot
        ):
            return context
        await observer.observe_official_message(incoming, explicitly_addressed=True)
        if (
            not incoming.direct_mentions
            and incoming.reply_to_id is None
            and parse_rank_player_target_command(incoming.text) is not None
        ):
            target = await observer.missing_member_target(incoming)
            if target is not None:
                return replace(context, verified_member_mentions=(target,))
        return context
