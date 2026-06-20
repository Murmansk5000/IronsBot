from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from ironsbot.shared.features import get_superuser_ids, groups_for_feature

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


class StartupNoticeConfig(Protocol):
    enabled: bool


@dataclass(frozen=True, slots=True)
class StartupNoticeTargets:
    private_user_ids: list[int]
    group_ids: list[int]

    @property
    def is_empty(self) -> bool:
        return not self.private_user_ids and not self.group_ids


@dataclass(slots=True)
class StartupNoticeState:
    sent: bool = False
    sending: bool = False


@dataclass(slots=True)
class StartupNoticeService:
    state: StartupNoticeState = field(default_factory=StartupNoticeState)
    superuser_loader: Callable[[], set[int]] = get_superuser_ids
    feature_group_loader: Callable[[str], list[int]] = groups_for_feature

    def should_send(self, config: StartupNoticeConfig) -> bool:
        return config.enabled and not self.state.sent and not self.state.sending

    def begin_send(self) -> None:
        self.state.sending = True

    def get_targets(self) -> StartupNoticeTargets:
        return StartupNoticeTargets(
            private_user_ids=sorted(self.superuser_loader()),
            group_ids=self.feature_group_loader("admin_notice"),
        )

    def mark_result(self, succeeded: Sequence[object]) -> None:
        if succeeded:
            self.state.sent = True

    def finish_send(self) -> None:
        if not self.state.sent:
            self.state.sending = False
