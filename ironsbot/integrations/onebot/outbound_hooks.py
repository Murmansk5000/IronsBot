# SPDX-License-Identifier: MIT
"""Decode native API calls and associate receipts with shared send permits."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment
from nonebot.exception import MockApiException
from nonebot.log import logger
from nonebot.matcher import current_event

from ironsbot.core.platform import reference_digest
from ironsbot.integrations.onebot.identity import onebot_actor_ref
from ironsbot.integrations.onebot.receipts import (
    onebot_send_failure,
    onebot_send_result,
)

if TYPE_CHECKING:
    from nonebot.adapters import Bot as AdapterBot

    from ironsbot.core.platform import ActorRef
    from ironsbot.services.messaging.outbound_limits import (
        GroupOutboundRateLimitService,
        OutboundPermit,
    )

_SUPPORTED_GROUP_SEND_APIS = frozenset(("send_msg", "send_group_msg"))
_SUPPRESSED_RESULT_KEY = "_ironsbot_outbound_suppressed"


@dataclass(slots=True)
class OneBotOutboundRateLimitHooks:
    service: GroupOutboundRateLimitService
    _permits: dict[int, OutboundPermit] = field(default_factory=dict, init=False)

    async def check(self, bot: AdapterBot, api: str, data: dict[str, Any]) -> None:
        if not isinstance(bot, Bot) or api not in _SUPPORTED_GROUP_SEND_APIS:
            return
        group_id = _extract_group_id(api, data)
        if group_id is None:
            return
        if self.service.owns_send(group_id):
            return
        decision = await self.service.acquire_send(group_id, actor=_reply_actor())
        if not decision.allowed:
            logger.info(
                "group message suppressed by outbound rate limit: "
                "conversation_ref={}, api={}",
                reference_digest(str(group_id)),
                api,
            )
            raise MockApiException(
                {
                    _SUPPRESSED_RESULT_KEY: True,
                    "group_id": group_id,
                    "reason": decision.reason or "rate_limit",
                }
            )
        permit = decision.permit
        if permit is not None:
            self._permits[id(data)] = permit
            if permit.append_cooldown_notice:
                message = Message(data.get("message", ""))
                message += MessageSegment.text(
                    f"\n\n{self.service.config.cooldown_message}"
                )
                data["message"] = message

    async def finalize(
        self,
        bot: AdapterBot,
        exception: Exception | None,
        api: str,
        data: dict[str, Any],
        result: Any,
    ) -> None:
        if not isinstance(bot, Bot) or api not in _SUPPORTED_GROUP_SEND_APIS:
            return
        permit = self._permits.pop(id(data), None)
        if permit is None:
            return
        if exception is not None:
            failure = onebot_send_failure(exception)
            self.service.settle_send(
                permit, failure.result, interrupted=failure.interrupted
            )
        else:
            self.service.settle_send(permit, onebot_send_result(result))

    def install(self) -> None:
        Bot.on_calling_api(self.check)
        Bot.on_called_api(self.finalize)


def _extract_group_id(api: str, data: dict[str, Any]) -> int | None:
    if not (
        api == "send_group_msg"
        or (
            api == "send_msg"
            and (
                data.get("message_type") == "group" or data.get("group_id") is not None
            )
        )
    ):
        return None
    raw_group_id = data.get("group_id")
    if raw_group_id is None:
        return None
    try:
        group_id = int(raw_group_id)
    except (TypeError, ValueError):
        return None
    return group_id if group_id > 0 else None


def _reply_actor() -> ActorRef | None:
    try:
        event = current_event.get()
    except LookupError:
        return None
    raw_user_id = getattr(event, "user_id", None)
    if not isinstance(raw_user_id, int | str):
        return None
    return onebot_actor_ref(str(raw_user_id))
