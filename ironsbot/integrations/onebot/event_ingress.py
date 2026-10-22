# SPDX-License-Identifier: MIT
"""OneBot protocol decoding and framework hooks for public admission."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    Bot,
    Event,
    GroupMessageEvent,
    Message,
    MessageEvent,
)
from nonebot.exception import IgnoredException
from nonebot.message import event_preprocessor
from nonebot.typing import T_State  # noqa: TC002 - native preprocessor injection

from ironsbot.integrations.onebot.ingress_facts import (
    OneBotMessageOrigin,
    onebot_admission_input,
)
from ironsbot.integrations.onebot.message_input import message_input_facts
from ironsbot.integrations.onebot.self_commands import SentGroupMessageEvent
from ironsbot.services.onebot_admission import OneBotAdmissionInput

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.onebot_admission import OneBotAdmissionService

logger = logging.getLogger(__name__)
ADMITTED_MESSAGE_KEY = "_ironsbot_admitted_message"


@dataclass(frozen=True, slots=True)
class AdmittedOneBotMessage:
    event: MessageEvent
    context: MessageInputContext


@dataclass(frozen=True, slots=True)
class OneBotEventIngress:
    admission: OneBotAdmissionService

    async def process(self, event: Event) -> MessageInputContext | None:
        try:
            incoming = _decode(event)
        except Exception as error:  # noqa: BLE001 - malformed transport payload is not a command
            logger.warning(
                "OneBot input decoding failed: error_type=%s", type(error).__name__
            )
            msg = "Invalid OneBot input facts"
            raise IgnoredException(msg) from None
        decision = await self.admission.decide(incoming)
        if decision.rejection is not None:
            raise IgnoredException(decision.rejection.value)
        return decision.context

    def install(self) -> None:
        ingress = self

        @event_preprocessor
        async def enforce_onebot_ingress(
            bot: Bot, event: Event, state: T_State
        ) -> None:
            state.pop(ADMITTED_MESSAGE_KEY, None)
            if bot.self_id != str(event.self_id):
                msg = "Input account does not match receiving connection"
                raise IgnoredException(msg)
            context = await ingress.process(event)
            if isinstance(event, MessageEvent) and context is not None:
                state[ADMITTED_MESSAGE_KEY] = AdmittedOneBotMessage(event, context)


def _decode(event: Event) -> OneBotAdmissionInput:
    if isinstance(event, SentGroupMessageEvent):
        origin = OneBotMessageOrigin.SENT_GROUP
    elif isinstance(event, GroupMessageEvent):
        origin = OneBotMessageOrigin.GROUP
    elif isinstance(event, MessageEvent):
        origin = OneBotMessageOrigin.PRIVATE
    elif (
        event.post_type == "message_sent"
        and getattr(event, "message_type", None) == "group"
        and isinstance(getattr(event, "message", None), (Message, list))
    ):
        origin = OneBotMessageOrigin.SENT_GROUP
    else:
        return OneBotAdmissionInput()
    return onebot_admission_input(message_input_facts(event), origin)
