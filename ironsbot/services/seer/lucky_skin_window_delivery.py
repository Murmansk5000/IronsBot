# SPDX-License-Identifier: MIT
"""Address-aware, receipt-committed daily lucky-window delivery."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import DeliveryFailureKind, OutboundMessage
from ironsbot.core.platform import (
    ActorRef,
    IncomingMessageRef,
    private_conversation_for_actor,
    reference_digest,
)
from ironsbot.services.seer.lucky_skin_window import LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.core.platform import ActorPrincipal
    from ironsbot.services.messaging.admin_notice import AdminNoticeService
    from ironsbot.services.messaging.daily_delivery import DailyDeliveryStore
    from ironsbot.services.messaging.proactive_delivery import ProactiveMessageDelivery
    from ironsbot.services.messaging.subscriptions import PushSubscriptionRepository
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.private_conversation_routes import PrivateConversationRoutes
    from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowResult

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class LuckySkinWindowOutboundSender:
    delivery: ProactiveMessageDelivery
    subscriptions: PushSubscriptionRepository
    claims: DailyDeliveryStore
    private_routes: PrivateConversationRoutes
    sessions: PortableQuerySessions
    principal_for: Callable[[ActorRef], ActorPrincipal]
    render: (
        Callable[
            [MessageInputContext, ActorRef, LuckySkinWindowResult],
            Awaitable[OutboundMessage],
        ]
        | None
    ) = None
    admin_notices: AdminNoticeService | None = None

    async def send_daily_notice(
        self, actor: ActorRef, message: str | LuckySkinWindowResult, *, day: str
    ) -> bool:
        source = private_conversation_for_actor(actor)
        conversation = self.private_routes.resolve(source)
        if any(
            self.subscriptions.is_unsubscribed(
                target, LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY
            )
            for target in {source, conversation}
        ):
            return False
        if not self.delivery.messenger.capabilities_for(
            conversation
        ).can_send_proactively:
            _LOGGER.warning(
                "daily lucky route unavailable: day=%s recipient=%s platform=%s",
                day,
                reference_digest(actor.id),
                conversation.platform.value,
            )
            if self.admin_notices is not None:
                try:
                    await self.admin_notices.send_private_to_superusers(
                        "⚠️ 橱窗私聊推送未发送\n"
                        f"日期：{day}\n"
                        f"目标用户：{actor.id}\n"
                        "原因：没有可用的官方机器人私聊地址或主动发送能力。\n"
                        "执行机器人：未确定",
                        subscription_key="admin_notice",
                        action_name="lucky skin window route failure notice",
                        interval_seconds=0,
                    )
                except Exception:
                    _LOGGER.exception("daily lucky route failure notice failed")
            return False
        principal = self.principal_for(actor)
        key = f"lucky:{principal.kind}:{principal.id}"
        if not self.claims.claim(key, day):
            return False
        context = MessageInputContext(
            IncomingMessageRef(
                conversation.platform,
                ActorRef(
                    conversation.platform,
                    conversation.id,
                    account_id=conversation.account_id,
                ),
                conversation,
                f"lucky:{day}",
                "橱窗",
            ),
            mentions_bot=False,
        )
        outbound = None
        attempted = False
        delivered = False
        try:
            outbound = await self._render_message(context, actor, message)
            attempted = True
            summary = await self.delivery.send(
                outbound,
                (conversation,),
                action_name="lucky skin window daily notice",
                interval_seconds=0,
                subscription_key=LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
                max_attempts=1,
            )
            receipt = dict(summary.results).get(conversation)
            if receipt is not None and receipt.delivered:
                self.claims.finish(
                    key, day, "failed" if isinstance(message, str) else "success"
                )
                self.sessions.record_proactive_delivery(context, outbound, receipt)
                delivered = True
            else:
                uncertain = bool(summary.uncertain) or (
                    receipt is not None
                    and receipt.failure_kind is DeliveryFailureKind.UNCERTAIN
                )
                self.claims.finish(key, day, "uncertain" if uncertain else "failed")
        except BaseException:
            self.claims.finish(key, day, "uncertain" if attempted else "failed")
            raise
        finally:
            if not delivered and outbound is not None and outbound.prompt is not None:
                self.sessions.discard_prompt(context, outbound.prompt.id)
        _LOGGER.info(
            "daily lucky delivery completed: day=%s recipient=%s delivered=%s",
            day,
            reference_digest(actor.id),
            delivered,
        )
        return delivered

    async def _render_message(
        self,
        context: MessageInputContext,
        actor: ActorRef,
        message: str | LuckySkinWindowResult,
    ) -> OutboundMessage:
        if isinstance(message, str):
            return OutboundMessage.from_text(message)
        if self.render is None:
            raise RuntimeError("daily lucky menu renderer is not configured")  # noqa: TRY003
        return await self.render(context, actor, message)
