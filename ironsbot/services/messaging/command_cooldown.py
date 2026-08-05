# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Protocol

from ironsbot.core.response_admission import (
    FeedbackOnce,
    ResponseAdmissionDecision,
)

_ENTRY_PRUNE_INTERVAL_SECONDS = 60.0


class CommandCooldownWindow(Protocol):
    window_seconds: float
    max_requests: int


class CommandCooldownConfig(Protocol):
    enabled: bool
    in_progress_message: str
    cooldown_message: str

    def windows_for(
        self,
        command_id: str,
    ) -> tuple[CommandCooldownWindow, ...]: ...


class SuperuserLookup(Protocol):
    def is_superuser(self, user_id: int) -> bool: ...


@dataclass(frozen=True, slots=True)
class CommandCooldownToken:
    user_id: int
    command_id: str


CommandCooldownDecision = ResponseAdmissionDecision


@dataclass(slots=True)
class _CommandCooldownEntry:
    in_progress: bool = False
    completed_at: deque[float] = field(default_factory=deque)
    feedback: FeedbackOnce = field(default_factory=FeedbackOnce)


@dataclass(slots=True)
class CommandCooldownService:
    config: CommandCooldownConfig
    features: SuperuserLookup
    _entries: dict[tuple[int, str], _CommandCooldownEntry] = field(
        default_factory=dict
    )
    _last_prune_at: float = 0.0

    def admit(
        self,
        *,
        user_id: int,
        command_id: str,
        now: float | None = None,
    ) -> CommandCooldownDecision:
        windows = self.config.windows_for(command_id)
        if (
            not self.config.enabled
            or not windows
            or self.features.is_superuser(user_id)
        ):
            return CommandCooldownDecision(allowed=True)

        current_time = time.monotonic() if now is None else now
        self._prune_expired(current_time)
        key = (user_id, command_id)
        entry = self._entries.setdefault(key, _CommandCooldownEntry())
        self._trim_entry(entry, windows, current_time)

        if entry.in_progress:
            return CommandCooldownDecision(
                allowed=False,
                feedback=entry.feedback.take(self.config.in_progress_message),
            )

        remaining_seconds = self._remaining_seconds(entry, windows, current_time)
        if remaining_seconds is not None:
            return CommandCooldownDecision(
                allowed=False,
                feedback=entry.feedback.take(
                    self.config.cooldown_message.format(
                        remaining_seconds=remaining_seconds,
                    )
                ),
            )

        entry.in_progress = True
        entry.feedback = FeedbackOnce()
        return CommandCooldownDecision(
            allowed=True,
            token=CommandCooldownToken(
                user_id,
                command_id,
            ),
        )

    def finish(
        self,
        token: object,
        *,
        now: float | None = None,
    ) -> None:
        if not isinstance(token, CommandCooldownToken):
            return
        entry = self._entries.get((token.user_id, token.command_id))
        if entry is None or not entry.in_progress:
            return
        current_time = time.monotonic() if now is None else now
        entry.in_progress = False
        entry.completed_at.append(current_time)
        entry.feedback = FeedbackOnce()

    def release(self, token: object) -> None:
        """Drop an unhandled reservation without consuming a cooldown slot."""

        if not isinstance(token, CommandCooldownToken):
            return
        entry = self._entries.get((token.user_id, token.command_id))
        if entry is None or not entry.in_progress:
            return
        entry.in_progress = False
        entry.feedback = FeedbackOnce()

    def reset(self) -> None:
        self._entries.clear()
        self._last_prune_at = 0.0

    def _prune_expired(self, current_time: float) -> None:
        if current_time - self._last_prune_at < _ENTRY_PRUNE_INTERVAL_SECONDS:
            return
        self._last_prune_at = current_time
        retained: dict[tuple[int, str], _CommandCooldownEntry] = {}
        for key, entry in self._entries.items():
            self._trim_entry(entry, self.config.windows_for(key[1]), current_time)
            if entry.in_progress or entry.completed_at:
                retained[key] = entry
        self._entries = retained

    @staticmethod
    def _trim_entry(
        entry: _CommandCooldownEntry,
        windows: tuple[CommandCooldownWindow, ...],
        current_time: float,
    ) -> None:
        if not windows:
            entry.completed_at.clear()
            return
        oldest_allowed = current_time - max(
            window.window_seconds for window in windows
        )
        while entry.completed_at and entry.completed_at[0] <= oldest_allowed:
            entry.completed_at.popleft()

    @staticmethod
    def _remaining_seconds(
        entry: _CommandCooldownEntry,
        windows: tuple[CommandCooldownWindow, ...],
        current_time: float,
    ) -> int | None:
        remaining_values: list[float] = []
        for window in windows:
            timestamps = [
                timestamp
                for timestamp in entry.completed_at
                if timestamp > current_time - window.window_seconds
            ]
            if len(timestamps) < window.max_requests:
                continue
            oldest_blocking_timestamp = timestamps[-window.max_requests]
            remaining_values.append(
                oldest_blocking_timestamp + window.window_seconds - current_time
            )
        if not remaining_values:
            return None
        return max(1, math.ceil(max(remaining_values)))
