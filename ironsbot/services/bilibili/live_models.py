# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ironsbot.core.platform import ConversationRef


class LiveStatusUnavailableError(RuntimeError):
    """A failed observation is not evidence of going offline."""

    @classmethod
    def http(cls, status: int) -> LiveStatusUnavailableError:
        return cls(f"live status HTTP {status}")

    @classmethod
    def invalid(cls) -> LiveStatusUnavailableError:
        return cls("live status payload unavailable")


@dataclass(slots=True)
class LiveSchedule:
    key: str
    starts_at: float
    published_at: float
    sources: list[str] = field(default_factory=list)
    ended: bool = False
    before_created: bool = False
    before_notice_key: str = ""
    start_created: bool = False


@dataclass(slots=True)
class LiveAccount:
    uid: int
    status: int | None = None
    checked_at: float = 0
    session: str = ""
    live_time: int = 0
    offline_count: int = 0
    room_id: int = 0
    observed_live: bool | None = None
    retry_after: float = 0
    failures: int = 0
    schedules: list[LiveSchedule] = field(default_factory=list)
    latest_preview_at: float = 0
    source_revisions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LiveObservation:
    uid: int
    room_id: int
    live: bool
    live_time: int
    title: str
    name: str


@dataclass(frozen=True, slots=True)
class LiveNotice:
    key: str
    uid: int
    kind: str
    schedule: str
    session: str
    created_at: float
    expires_at: float
    text: str
    targets: tuple[ConversationRef, ...]


class LiveStateStore(Protocol):
    def account(self, uid: int) -> LiveAccount: ...
    def save(
        self, account: LiveAccount, notices: tuple[LiveNotice, ...] = ()
    ) -> None: ...
    def add_notice(self, notice: LiveNotice) -> None: ...
    def notices(self, now: float) -> list[LiveNotice]: ...
    def notice(self, key: str) -> LiveNotice | None: ...
    def complete(self, key: str) -> None: ...
    def prune(self, now: float) -> None: ...
