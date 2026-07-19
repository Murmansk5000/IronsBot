# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ironsbot.services.messaging.admin_notice import AdminNoticeService


@dataclass(frozen=True, slots=True)
class StartupNoticePart:
    subscription_key: str
    action_name: str
    message: str


@dataclass(slots=True)
class StartupNoticeService:
    admin_notices: AdminNoticeService
    parts: list[StartupNoticePart] = field(default_factory=list)
    sent: bool = False
    sending: bool = False

    def add(self, subscription_key: str, action_name: str, message: str | None) -> None:
        if message:
            self.parts.append(
                StartupNoticePart(
                    subscription_key=subscription_key,
                    action_name=action_name,
                    message=message,
                )
            )

    def should_send(self, *, enabled: bool) -> bool:
        return enabled and not self.sent and not self.sending

    def begin_send(self) -> None:
        self.sending = True

    def mark_result(self, succeeded: Sequence[object]) -> None:
        if succeeded:
            self.sent = True

    def finish_send(self) -> None:
        self.sending = False
