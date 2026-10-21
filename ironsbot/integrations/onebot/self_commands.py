# SPDX-License-Identifier: MIT
"""Opt-in own-account commands at the OneBot transport boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import Adapter, Event, GroupMessageEvent, Message
from pydantic import PrivateAttr

from ironsbot.core.own_commands import OwnAccountInput
from ironsbot.core.platform import ConversationRef, Platform

if TYPE_CHECKING:
    from ironsbot.core.own_commands import OwnAccountCommand


class SelfCommandEvent(GroupMessageEvent):
    _accepted: bool = PrivateAttr(default=False)
    _admin_binding: bool = PrivateAttr(default=False)

    def apply_command(self, command: OwnAccountCommand) -> None:
        references = Message(
            segment
            for segment in (self.original_message or self.message)
            if segment.type in {"reply", "at"}
        )
        self.message = references + Message(command.text)
        self.original_message = self.message.copy()
        self.raw_message = command.text
        self.to_me = False
        self._accepted = True
        self._admin_binding = command.admin_binding

    @property
    def accepted(self) -> bool:
        return self._accepted

    @property
    def admin_binding(self) -> bool:
        return self._admin_binding


class SelfCommandAdapter(Adapter):
    @classmethod
    def json_to_event(cls, json_data: Any) -> Event | None:
        if (
            isinstance(json_data, dict)
            and json_data.get("post_type") == "message_sent"
            and json_data.get("message_type") == "group"
            and json_data.get("user_id") == json_data.get("self_id")
        ):
            return SelfCommandEvent.model_validate(
                {**json_data, "post_type": "message"}
            )
        return super().json_to_event(json_data)


def is_unaccepted_self_message(event: GroupMessageEvent | Event) -> bool:
    return getattr(event, "user_id", None) == event.self_id and not (
        isinstance(event, SelfCommandEvent) and event.accepted
    )


def own_account_input(event: SelfCommandEvent) -> OwnAccountInput:
    return _snapshot(
        str(event.self_id),
        ConversationRef(Platform.ONEBOT, "group", str(event.group_id)),
        event.original_message or event.message,
        is_own_message=event.user_id == event.self_id,
    )


def outbound_own_account_input(
    account_id: str, conversation: ConversationRef, message: Message
) -> OwnAccountInput | None:
    if conversation.platform is not Platform.ONEBOT or conversation.kind != "group":
        return None
    return _snapshot(account_id, conversation, message, is_own_message=True)


def _snapshot(
    account_id: str,
    conversation: ConversationRef,
    message: Message,
    *,
    is_own_message: bool,
) -> OwnAccountInput:
    return OwnAccountInput(
        account_id,
        conversation,
        is_own_message,
        message.extract_plain_text(),
        tuple(
            str(segment.data.get("qq", ""))
            for segment in message
            if segment.type == "at"
        ),
        any(segment.type not in {"text", "reply", "at"} for segment in message),
    )
