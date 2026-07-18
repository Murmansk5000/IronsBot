# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.shared.messaging.admin_notice import (
    AdminNoticeTargets,
    admin_notice_targets,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


@dataclass(frozen=True, slots=True)
class StartupNoticeProvider:
    subscription_key: str
    action_name: str
    get_message: Callable[[], str | None]


@dataclass(slots=True)
class StartupNoticeService:
    target_loader: Callable[[], AdminNoticeTargets] = admin_notice_targets
    sent: bool = False
    sending: bool = False

    def should_send(self, *, enabled: bool) -> bool:
        return enabled and not self.sent and not self.sending

    def begin_send(self) -> None:
        self.sending = True

    def get_targets(self) -> AdminNoticeTargets:
        return self.target_loader()

    def mark_result(self, succeeded: Sequence[object]) -> None:
        if succeeded:
            self.sent = True

    def finish_send(self) -> None:
        self.sending = False
