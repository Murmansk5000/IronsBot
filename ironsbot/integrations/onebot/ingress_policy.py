# SPDX-License-Identifier: MIT
"""OneBot ingress gate for interactive and silent-verifier deployments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Event, GroupMessageEvent
from nonebot.exception import IgnoredException
from nonebot.message import event_preprocessor

from ironsbot.services.identity_observation import OneBotReplyObservation

if TYPE_CHECKING:
    from ironsbot.services.identity_observation import (
        SilentIdentityObservationService,
    )

_SILENT_REASON = "OneBot is running in silent verifier mode"


@dataclass(frozen=True, slots=True)
class OneBotIngressPolicy:
    messages_enabled: bool
    identity_observer: SilentIdentityObservationService | None = None

    async def process(self, event: Event) -> None:
        if self.identity_observer is not None and isinstance(
            event,
            GroupMessageEvent,
        ):
            await self.identity_observer.observe_onebot(
                OneBotReplyObservation(
                    sender_id=event.user_id,
                    group_id=event.group_id,
                    mentioned_qq_ids=_mentioned_qq_ids(event),
                    text=event.get_plaintext(),
                )
            )
        if not self.messages_enabled:
            raise IgnoredException(_SILENT_REASON)

    def install(self) -> None:
        policy = self

        @event_preprocessor
        async def enforce_onebot_ingress(event: Event) -> None:
            await policy.process(event)


def _mentioned_qq_ids(event: GroupMessageEvent) -> tuple[str, ...]:
    values: list[str] = []
    message = event.original_message or event.message
    for segment in message:
        if segment.type != "at":
            continue
        value = str(segment.data.get("qq", "")).strip()
        if value.isdecimal() and value not in values:
            values.append(value)
    return tuple(values)
