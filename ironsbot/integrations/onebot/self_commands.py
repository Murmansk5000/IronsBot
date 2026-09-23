# SPDX-License-Identifier: MIT
"""Opt-in own-account commands at the OneBot transport boundary."""

from __future__ import annotations

from collections import OrderedDict
from time import monotonic
from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import Adapter, Event, GroupMessageEvent, Message
from pydantic import PrivateAttr

if TYPE_CHECKING:
    from nonebot.adapters import Bot

    from ironsbot.config.models.transport import SelfCommandsConfig

_RETENTION_SECONDS = 600
_MAX_RECORDS = 4096


class SelfCommandEvent(GroupMessageEvent):
    _accepted: bool = PrivateAttr(default=False)

    def accept(self, text: str) -> None:
        references = Message(
            segment for segment in (self.original_message or self.message)
            if segment.type == "reply"
        )
        self.message = references + Message(text)
        self.original_message = self.message.copy()
        self.raw_message = text
        self.to_me = False
        self._accepted = True

    @property
    def accepted(self) -> bool:
        return self._accepted


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


class SelfCommandGate:
    """Bounded event and outbound echo retention, owned by one application."""

    def __init__(self, config: SelfCommandsConfig) -> None:
        self.config = config
        self._recent: OrderedDict[tuple[str, str, str, str], float] = OrderedDict()

    def _prune(self, now: float) -> None:
        while self._recent:
            if (
                next(iter(self._recent.values())) > now - _RETENTION_SECONDS
                and len(self._recent) <= _MAX_RECORDS
            ):
                break
            self._recent.popitem(last=False)

    def _remember(self, key: tuple[str, str, str, str], now: float) -> None:
        self._recent[key] = now
        self._recent.move_to_end(key)
        self._prune(now)

    def accept(self, event: SelfCommandEvent) -> bool:
        if not self.config.enabled or event.user_id != event.self_id:
            return False
        message = event.original_message or event.message
        if any(segment.type not in {"text", "reply"} for segment in message):
            return False
        text = message.extract_plain_text()
        prefix = next((p for p in self.config.prefixes if text.startswith(p)), None)
        if prefix is None or not (command := text[len(prefix):].strip()):
            return False
        now = monotonic()
        self._prune(now)
        scope = (str(event.self_id), str(event.group_id))
        key = (*scope, "event", str(event.message_id))
        if key in self._recent or (*scope, "outbound", text) in self._recent:
            return False
        self._remember(key, now)
        event.accept(command)
        return True

    async def record_outbound(self, bot: Bot, api: str, data: dict[str, Any]) -> None:
        if not self.config.enabled or api not in {"send_group_msg", "send_msg"}:
            return
        group_id = data.get("group_id")
        if group_id is None or "message" not in data:
            return
        text = Message(data["message"]).extract_plain_text()
        if any(text.startswith(prefix) for prefix in self.config.prefixes):
            self._remember((bot.self_id, str(group_id), "outbound", text), monotonic())
