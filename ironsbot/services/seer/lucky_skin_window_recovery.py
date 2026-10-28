# SPDX-License-Identifier: MIT
"""Restore a frozen lucky-window menu without requerying or rerendering it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.platform import ActorRef, IncomingMessageRef, Platform
from ironsbot.services.portable_query_sessions import PortableMenuSpec
from ironsbot.services.seer.pet_query import PetImageSelection
from ironsbot.services.seer.query_result import QueryChoice

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.outbound import OutboundMessage, SendResult
    from ironsbot.services.messaging.daily_delivery import DailyDeliveryStore
    from ironsbot.services.messaging.delivery_tasks import StoredDelivery
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowService
    from ironsbot.services.seer.pet_query import PetQueryService


@dataclass(frozen=True, slots=True)
class LuckyWindowRecovery:
    service: LuckySkinWindowService
    pet: PetQueryService
    features: FeatureService
    sessions: PortableQuerySessions
    claims: DailyDeliveryStore

    @staticmethod
    def matches(task: StoredDelivery) -> bool:
        return task.intent.key.startswith("lucky:")

    def allowed(self, task: StoredDelivery) -> bool:
        if not self.matches(task):
            return True
        if not task.intent.source_id or task.intent.source_platform not in {
            platform.value for platform in Platform
        }:
            return False
        actor = ActorRef(
            Platform(task.intent.source_platform),
            task.intent.source_id,
            account_id=task.intent.source_account,
        )
        return self.service.is_eligible_actor(actor)

    @staticmethod
    def context(task: StoredDelivery) -> MessageInputContext:
        target = task.conversation
        return MessageInputContext(
            IncomingMessageRef(
                target.platform,
                ActorRef(target.platform, target.id, account_id=target.account_id),
                target,
                task.id,
                "橱窗",
            ),
            mentions_bot=False,
        )

    async def prepare(self, task: StoredDelivery) -> OutboundMessage:
        if not self.matches(task) or not task.intent.skin_choices:
            return task.message
        choices = tuple(
            QueryChoice(
                name,
                f"皮肤ID：{skin_id}",
                PetImageSelection(resource_id, name, skin_id=skin_id),
            )
            for skin_id, resource_id, name in task.intent.skin_choices
        )

        async def select(
            choice: QueryChoice[PetImageSelection], _ctx: MessageInputContext
        ) -> OutboundMessage:
            from ironsbot.core.outbound import OutboundMessage

            result = await self.pet.select_image(choice.value)
            return (
                result.reply.to_outbound()
                if result.reply
                else OutboundMessage.from_text(result.message or "皮肤详情暂时不可用。")
            )

        return self.sessions.offer_menu(
            self.context(task),
            PortableMenuSpec(
                choices=choices,
                select=select,
                prompt=task.message,
                labels=tuple(choice.name for choice in choices),
                shareable=True,
                keep_open=True,
                access=lambda ctx: self.features.is_feature_allowed(
                    ctx.message.actor,
                    ctx.message.conversation,
                    "seer_pet",
                ),
            ),
        )

    def finished(
        self, task: StoredDelivery, message: OutboundMessage, receipt: SendResult
    ) -> None:
        if not self.matches(task):
            return
        context = self.context(task)
        if receipt.delivered:
            key, day = task.intent.key.rsplit(":", 1)
            self.claims.claim(key, day)
            self.claims.finish(key, day, "success")
            self.sessions.record_proactive_delivery(context, message, receipt)
        elif message.prompt is not None:
            self.sessions.discard_prompt(context, message.prompt.id)
