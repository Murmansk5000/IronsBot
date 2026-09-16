# SPDX-License-Identifier: MIT
"""OneBot ingress gate for interactive and silent-verifier deployments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Event, GroupMessageEvent
from nonebot.exception import IgnoredException
from nonebot.message import event_preprocessor

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
            await self.identity_observer.observe_onebot(event)
        if not self.messages_enabled:
            raise IgnoredException(_SILENT_REASON)

    def install(self) -> None:
        policy = self

        @event_preprocessor
        async def enforce_onebot_ingress(event: Event) -> None:
            await policy.process(event)
