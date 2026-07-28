# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.log import logger

from ironsbot.core.messaging import (
    MessageTarget,
    TargetSendSummary,
    broadcast_targets,
)

from .outbound import (
    GroupOutboundRateLimitService,
    is_outbound_suppressed_result,
    use_preacquired_push_permit,
)

if TYPE_CHECKING:
    from ironsbot.config.models.messaging import PushUnsubscribeConfig
    from ironsbot.services.messaging.subscriptions import (
        PushDeliverySubscriptions,
        PushTargetType,
    )

    from .router import BotRouter

MessageLimiter = Callable[[str | Message, MessageTarget], str | Message]
PUSH_SUBSCRIPTION_HINT_KEY = "push_subscription_hint"


def _copy_outbound_message(message: str | Message) -> str | Message:
    return message.copy() if isinstance(message, Message) else message


def _build_message(
    content: str | Message,
    at_user_ids: Iterable[int],
) -> Message:
    message = Message()
    for user_id in dict.fromkeys(at_user_ids):
        message += MessageSegment.at(user_id)
        message += MessageSegment.text(" ")
    message += (
        content
        if isinstance(content, Message)
        else MessageSegment.text(content.replace("\\n", "\n"))
    )
    return message


def _append_unsubscribe_hint(
    message: str | Message,
    config: PushUnsubscribeConfig,
    target_type: PushTargetType,
    target_id: int,
    store: PushDeliverySubscriptions,
) -> str | Message:
    hint = (config.group_hint if target_type == "group" else config.hint).strip()
    if not hint or not store.mark_daily_hint_sent(
        target_type,
        target_id,
        PUSH_SUBSCRIPTION_HINT_KEY,
    ):
        return message.rstrip() if isinstance(message, str) else message
    if isinstance(message, Message):
        if hint not in str(message):
            message += MessageSegment.text(f"\n\n{hint}")
        return message
    text = message.rstrip()
    return text if hint in text else hint if not text else f"{text}\n\n{hint}"


class OneBotMessageSender(Protocol):
    async def send_private_msg(self, *, user_id: int, message: Message) -> object: ...

    async def send_group_msg(self, *, group_id: int, message: Message) -> object: ...


@dataclass(frozen=True, slots=True)
class OneBotDelivery:
    outbound: GroupOutboundRateLimitService
    push_unsubscribe: PushUnsubscribeConfig
    bot_router: BotRouter
    subscriptions: PushDeliverySubscriptions

    def default_bot(self) -> OneBotMessageSender | None:
        return self.bot_router.default_bot()

    def bot_for_target(self, target: MessageTarget) -> OneBotMessageSender | None:
        return self.bot_router.for_target(target)

    async def _send_target(  # noqa: PLR0913
        self,
        target: MessageTarget,
        message: str | Message,
        *,
        index: int,
        bot: OneBotMessageSender | None,
        action_name: str,
        interval_seconds: float,
        message_limiter: MessageLimiter | None,
        subscription_key: str | None,
    ) -> bool:
        if index > 0 and interval_seconds > 0:
            await asyncio.sleep(index * interval_seconds)

        target_bot = bot or self.bot_router.for_target(target)
        if target_bot is None:
            logger.warning(
                f"{action_name} has no connected bot for "
                f"{target.target_type} {target.target_id}"
            )
            return False

        limited_message = _copy_outbound_message(message)
        if message_limiter is not None:
            limited_message = message_limiter(limited_message, target)
        group_id = target.target_id if target.target_type == "group" else None
        if subscription_key:
            limited_message = _append_unsubscribe_hint(
                limited_message,
                self.push_unsubscribe,
                target.target_type,
                target.target_id,
                self.subscriptions,
            )
        rendered_message = _build_message(
            limited_message,
            (
                target.at_user_ids if target.target_type == "group" else ()
            ),
        )

        decision = await self.outbound.acquire_push(group_id, source=action_name)
        if not decision.allowed:
            logger.warning(
                f"{action_name} dropped by outbound push queue for "
                f"{target.target_type} {target.target_id}: {decision.reason}"
            )
            return False

        try:
            if target.target_type == "private":
                result = await target_bot.send_private_msg(
                    user_id=target.target_id,
                    message=rendered_message,
                )
            else:
                with use_preacquired_push_permit(self.outbound, decision.permit):
                    result = await target_bot.send_group_msg(
                        group_id=target.target_id,
                        message=rendered_message,
                    )
            if is_outbound_suppressed_result(result):
                self.outbound.rollback(decision.permit)
                logger.warning(
                    f"{action_name} was suppressed while sending to "
                    f"{target.target_type} {target.target_id}"
                )
                return False
        except Exception as e:  # noqa: BLE001
            self.outbound.rollback(decision.permit)
            logger.warning(
                f"{action_name} failed to send to {target.target_type} "
                f"{target.target_id} via bot "
                f"{getattr(target_bot, 'self_id', 'explicit')}: {e}"
            )
            return False

        logger.info(
            f"{action_name} sent to {target.target_type} {target.target_id} "
            f"via bot {getattr(target_bot, 'self_id', 'explicit')}"
        )
        return True

    async def send_targets(  # noqa: PLR0913
        self,
        targets: Iterable[MessageTarget],
        message: str | Message,
        *,
        bot: OneBotMessageSender | None = None,
        action_name: str = "message action",
        interval_seconds: float = 1.5,
        message_limiter: MessageLimiter | None = None,
        subscription_key: str | None = None,
    ) -> TargetSendSummary:
        selected = list(dict.fromkeys(targets))
        if subscription_key:
            selected = self._filter_subscribed_targets(selected, subscription_key)

        results = await asyncio.gather(
            *(
                self._send_target(
                    target,
                    message,
                    index=index,
                    bot=bot,
                    action_name=action_name,
                    interval_seconds=interval_seconds,
                    message_limiter=message_limiter,
                    subscription_key=subscription_key,
                )
                for index, target in enumerate(selected)
            )
        )
        return TargetSendSummary(
            [
                target
                for target, sent in zip(selected, results, strict=True)
                if sent
            ],
            [
                target
                for target, sent in zip(selected, results, strict=True)
                if not sent
            ],
        )

    async def broadcast(  # noqa: PLR0913
        self,
        message: str | Message,
        *,
        private_user_ids: Iterable[int] = (),
        group_ids: Iterable[int] = (),
        group_at_user_ids: Iterable[int] = (),
        bot: OneBotMessageSender | None = None,
        action_name: str = "message action",
        interval_seconds: float = 1.5,
        message_limiter: MessageLimiter | None = None,
        subscription_key: str | None = None,
    ) -> TargetSendSummary:
        return await self.send_targets(
            broadcast_targets(
                private_user_ids=private_user_ids,
                group_ids=group_ids,
                group_at_user_ids=group_at_user_ids,
            ),
            message,
            bot=bot,
            action_name=action_name,
            interval_seconds=interval_seconds,
            message_limiter=message_limiter,
            subscription_key=subscription_key,
        )

    def _filter_subscribed_targets(
        self,
        targets: list[MessageTarget],
        subscription_key: str,
    ) -> list[MessageTarget]:
        private_ids = set(
            self.subscriptions.filter_subscribed_user_ids(
                [
                    target.target_id
                    for target in targets
                    if target.target_type == "private"
                ],
                subscription_key,
            )
        )
        group_ids = set(
            self.subscriptions.filter_subscribed_group_ids(
                [
                    target.target_id
                    for target in targets
                    if target.target_type == "group"
                ],
                subscription_key,
            )
        )
        return [
            target
            for target in targets
            if (target.target_type == "private" and target.target_id in private_ids)
            or (target.target_type == "group" and target.target_id in group_ids)
        ]
