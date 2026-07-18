from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from ironsbot.shared.messaging.admin_notice import (
    AdminNoticeTargets,
    admin_notice_targets,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


class StartupNoticeConfig(Protocol):
    enabled: bool


@dataclass(frozen=True, slots=True)
class StartupNoticeProvider:
    subscription_key: str
    action_name: str
    get_message: Callable[[], str | None]


@dataclass(slots=True)
class StartupNoticeState:
    sent: bool = False
    sending: bool = False


@dataclass(slots=True)
class StartupNoticeService:
    state: StartupNoticeState = field(default_factory=StartupNoticeState)
    target_loader: Callable[[], AdminNoticeTargets] = admin_notice_targets

    def should_send(self, config: StartupNoticeConfig) -> bool:
        return config.enabled and not self.state.sent and not self.state.sending

    def begin_send(self) -> None:
        self.state.sending = True

    def get_targets(self) -> AdminNoticeTargets:
        return self.target_loader()

    def mark_result(self, succeeded: Sequence[object]) -> None:
        if succeeded:
            self.state.sent = True

    def finish_send(self) -> None:
        if not self.state.sent:
            self.state.sending = False
