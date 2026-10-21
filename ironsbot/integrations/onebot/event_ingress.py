# SPDX-License-Identifier: MIT
"""OneBot protocol decoding and framework hooks for public admission."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import (
    Bot,
    Event,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.exception import IgnoredException
from nonebot.message import event_preprocessor

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import ExecutionIdentity
from ironsbot.core.platform import IncomingMessageRef, Platform
from ironsbot.integrations.onebot.identity import (
    onebot_actor_ref,
    onebot_conversation_ref,
)
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.self_commands import (
    SelfCommandEvent,
    own_account_echo,
    own_account_input,
)
from ironsbot.services.identity_observation import OneBotGroupMessageObservation
from ironsbot.services.onebot_admission import OneBotAdmissionInput

if TYPE_CHECKING:
    from nonebot.adapters import Bot as AdapterBot

    from ironsbot.services.onebot_admission import OneBotAdmissionService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OneBotEventIngress:
    admission: OneBotAdmissionService

    async def process(self, event: Event) -> None:
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
        if decision.own_command is not None:
            if not isinstance(event, SelfCommandEvent):
                msg = "Unexpected OneBot own-command event type"
                raise IgnoredException(msg)
            event.apply_command(decision.own_command)

    def install(self) -> None:
        ingress = self
        self_commands = self.admission.self_commands
        if self.admission.messages_enabled and self_commands is not None:

            async def observe_outbound(
                bot: AdapterBot, api: str, data: dict[str, Any]
            ) -> None:
                if not isinstance(bot, Bot):
                    return
                echo = own_account_echo(bot, api, data)
                if echo is not None:
                    self_commands.record_outbound(echo)

            Bot.on_calling_api(observe_outbound)

        @event_preprocessor
        async def enforce_onebot_ingress(event: Event) -> None:
            await ingress.process(event)


def _decode(event: Event) -> OneBotAdmissionInput:
    observation = _group_message_observation(event)
    context = message_input_context(event) if isinstance(event, MessageEvent) else None
    if context is None and observation is not None:
        context = MessageInputContext(
            IncomingMessageRef(
                Platform.ONEBOT,
                onebot_actor_ref(observation.sender_id),
                onebot_conversation_ref(
                    observation.sender_id, group_id=observation.group_id
                ),
                observation.message_id,
                observation.text,
            ),
            mentions_bot=False,
            execution_identity=ExecutionIdentity(Platform.ONEBOT, str(event.self_id)),
        )
    return OneBotAdmissionInput(
        context=context,
        observation=observation,
        is_group_message=isinstance(event, GroupMessageEvent),
        own_input=own_account_input(event)
        if isinstance(event, SelfCommandEvent)
        else None,
    )


def _group_message_observation(
    event: Event,
) -> OneBotGroupMessageObservation | None:
    if isinstance(event, GroupMessageEvent):
        message = event.original_message or event.message
        sender_id = event.user_id
        group_id = event.group_id
        message_id = event.message_id
        reply_sender_id = (
            event.reply.sender.user_id if event.reply is not None else None
        )
    elif (
        event.post_type == "message_sent"
        and getattr(event, "message_type", None) == "group"
    ):
        message = _message_sent_content(event)
        sender_id = _integer_field(event, "user_id")
        group_id = _integer_field(event, "group_id")
        message_id = _integer_field(event, "message_id")
        reply_sender_id = None
        if (
            message is None
            or sender_id is None
            or group_id is None
            or message_id is None
        ):
            return None
    else:
        return None
    return OneBotGroupMessageObservation(
        sender_id=sender_id,
        self_id=event.self_id,
        group_id=group_id,
        mentioned_qq_ids=_mentioned_qq_ids(message, reply_sender_id=reply_sender_id),
        text=message.extract_plain_text(),
        message_id=str(message_id),
    )


def _message_sent_content(event: Event) -> Message | None:
    raw = getattr(event, "message", None)
    if isinstance(raw, Message):
        return raw
    if not isinstance(raw, list):
        return None
    segments: list[MessageSegment] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        segment_type = item.get("type")
        data = item.get("data")
        if not isinstance(segment_type, str) or not isinstance(data, dict):
            return None
        segments.append(MessageSegment(segment_type, data))
    return Message(segments)


def _integer_field(event: Event, name: str) -> int | None:
    value = getattr(event, name, None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _mentioned_qq_ids(
    message: Message,
    *,
    reply_sender_id: int | None,
) -> tuple[str, ...]:
    values: list[str] = []
    for segment in message:
        if segment.type != "at":
            continue
        value = str(segment.data.get("qq", "")).strip()
        if value.isdecimal() and value not in values:
            values.append(value)
    if not values and reply_sender_id is not None:
        value = str(reply_sender_id).strip()
        if value.isdecimal():
            values.append(value)
    return tuple(values)
