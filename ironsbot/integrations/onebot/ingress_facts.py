# SPDX-License-Identifier: MIT
"""Project one message snapshot into command and identity-observation facts."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from ironsbot.integrations.onebot.message_facts import decode_onebot_message
from ironsbot.integrations.onebot.message_segments import (
    onebot_message_text,
    onebot_own_account_input,
)
from ironsbot.services.identity_observation import OneBotGroupMessageObservation
from ironsbot.services.onebot_admission import OneBotAdmissionInput

if TYPE_CHECKING:
    from ironsbot.integrations.onebot.message_facts import OneBotMessageFacts


class OneBotMessageOrigin(str, Enum):
    GROUP = "received_group"
    PRIVATE = "received_private"
    SENT_GROUP = "sent_group"


def onebot_admission_input(
    facts: OneBotMessageFacts, origin: OneBotMessageOrigin
) -> OneBotAdmissionInput:
    if origin is OneBotMessageOrigin.PRIVATE and facts.group_id is not None:
        message = "OneBot private source cannot have group identity"
        raise ValueError(message)
    context = decode_onebot_message(facts)
    segments = facts.original_segments or facts.segments
    own_source = (
        origin is OneBotMessageOrigin.SENT_GROUP and facts.user_id == facts.account_id
    )
    observation = None
    if origin is not OneBotMessageOrigin.PRIVATE:
        if facts.group_id is None:
            message = "OneBot group source requires group identity"
            raise ValueError(message)
        targets = tuple(
            dict.fromkeys(
                str(segment["data"].get("qq", "")).strip()
                for segment in segments
                if segment["type"] == "at"
                and str(segment["data"].get("qq", "")).strip().isdecimal()
            )
        )
        if not targets and facts.reply_sender_id is not None:
            reply_sender = facts.reply_sender_id.strip()
            if reply_sender.isdecimal():
                targets = (reply_sender,)
        observation = OneBotGroupMessageObservation(
            sender_id=int(facts.user_id),
            self_id=int(facts.account_id),
            group_id=int(facts.group_id),
            mentioned_qq_ids=targets,
            text=onebot_message_text(segments),
            message_id=facts.message_id,
        )
    return OneBotAdmissionInput(
        context=context,
        observation=observation,
        is_group_message=origin is OneBotMessageOrigin.GROUP or own_source,
        own_input=onebot_own_account_input(
            facts.account_id,
            context.message.conversation,
            segments,
            is_own_message=True,
        )
        if own_source
        else None,
    )
