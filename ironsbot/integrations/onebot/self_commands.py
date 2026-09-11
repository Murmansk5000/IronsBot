# SPDX-License-Identifier: MIT
"""Opt-in demonstration commands from the connected bot's own QQ account."""

from __future__ import annotations

from collections import OrderedDict
from time import monotonic
from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import Adapter, Bot, Event, GroupMessageEvent, Message
from nonebot.exception import IgnoredException
from nonebot.message import event_preprocessor

if TYPE_CHECKING:
    from nonebot.adapters import Bot as BaseBot

    from ironsbot.config.models.settings import SelfCommandsConfig

MAX_RECENT_MESSAGES = 4096
RECENT_SECONDS = 600
GROUP_ONLY = "self commands are group-only"
UNAPPROVED = "unapproved or repeated self message"
TEXT_REQUIRED = "self commands require text input"


class SelfCommandAdapter(Adapter):
    @classmethod
    def json_to_event(cls, json_data: Any) -> Event | None:
        if isinstance(json_data, dict) and json_data.get("post_type") == "message_sent":
            if str(json_data.get("user_id")) != str(json_data.get("self_id")):
                return None
            json_data = {**json_data, "post_type": "message"}
        return super().json_to_event(json_data)


class SelfCommandGate:
    def __init__(
        self,
        config: SelfCommandsConfig,
        runtime_superuser_ids: set[int] | None = None,
    ) -> None:
        self.config = config
        self._runtime_superuser_ids = runtime_superuser_ids
        prefixes = [config.prefix] if isinstance(config.prefix, str) else config.prefix
        self._prefixes = tuple(sorted(set(prefixes), key=len, reverse=True))
        self._seen: OrderedDict[tuple[int, int, int], float] = OrderedDict()
        self._outbound: OrderedDict[tuple[int, int, str], float] = OrderedDict()

    def record_outbound(self, bot_id: int, group_id: int, message: Message) -> None:
        text = message.extract_plain_text()
        if self.config.enabled and text.startswith(self._prefixes):
            key = (bot_id, group_id, text)
            self._outbound[key] = monotonic()
            self._outbound.move_to_end(key)
            self._prune()

    def _prune(self) -> None:
        cutoff = monotonic() - RECENT_SECONDS
        for cache in (self._seen, self._outbound):
            while cache and (
                len(cache) > MAX_RECENT_MESSAGES or next(iter(cache.values())) < cutoff
            ):
                cache.popitem(last=False)

    def prepare(self, event: Event) -> None:
        if not isinstance(event, GroupMessageEvent):
            if getattr(event, "user_id", None) == event.self_id:
                raise IgnoredException(GROUP_ONLY)
            return
        if event.user_id != event.self_id:
            return
        self._prune()
        key = (event.self_id, event.group_id, event.message_id)
        text = event.get_plaintext()
        prefix = next((p for p in self._prefixes if text.startswith(p)), None)
        if (
            not self.config.enabled
            or key in self._seen
            or prefix is None
            or (event.self_id, event.group_id, text) in self._outbound
        ):
            raise IgnoredException(UNAPPROVED)
        self._seen[key] = monotonic()
        command = text[len(prefix) :].strip()
        if not command or any(
            segment.type not in {"text", "reply"} for segment in event.message
        ):
            raise IgnoredException(TEXT_REQUIRED)
        event.message = Message(command)
        event.original_message = Message(command)
        event.raw_message = command
        event.to_me = False
        object.__setattr__(event, "_ironsbot_self_command", True)
        if self.config.superuser and self._runtime_superuser_ids is not None:
            self._runtime_superuser_ids.add(int(event.self_id))


def install_self_commands(
    config: SelfCommandsConfig,
    runtime_superuser_ids: set[int] | None = None,
) -> None:
    gate = SelfCommandGate(config, runtime_superuser_ids)

    async def prepare(event: Event) -> None:
        gate.prepare(event)

    async def record(bot: BaseBot, api: str, data: dict[str, Any]) -> None:
        if not isinstance(bot, Bot):
            return
        if api not in {"send_group_msg", "send_msg"} or "group_id" not in data:
            return
        message = data.get("message")
        if message is not None:
            gate.record_outbound(
                int(bot.self_id), int(data["group_id"]), Message(message)
            )

    event_preprocessor(prepare)
    Bot.on_calling_api(record)
