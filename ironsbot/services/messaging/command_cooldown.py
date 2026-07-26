# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Protocol

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


@dataclass(frozen=True, slots=True)
class CommandCooldownDecision:
    allowed: bool
    token: CommandCooldownToken | None = None
    feedback: str | None = None


@dataclass(slots=True)
class _CommandCooldownEntry:
    active_token: CommandCooldownToken | None = None
    in_progress: bool = False
    completed_at: deque[float] = field(default_factory=deque)
    feedback_sent: bool = False


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
            feedback: str | None = None
            if not entry.feedback_sent:
                entry.feedback_sent = True
                feedback = self.config.in_progress_message
            return CommandCooldownDecision(allowed=False, feedback=feedback)

        remaining_seconds = self._remaining_seconds(entry, windows, current_time)
        if remaining_seconds is not None:
            feedback = None
            if not entry.feedback_sent:
                entry.feedback_sent = True
                feedback = self.config.cooldown_message.format(
                    remaining_seconds=remaining_seconds,
                )
            return CommandCooldownDecision(allowed=False, feedback=feedback)

        token = CommandCooldownToken(user_id, command_id)
        entry.active_token = token
        entry.in_progress = True
        entry.feedback_sent = False
        return CommandCooldownDecision(allowed=True, token=token)

    def bind_current_task(self, token: object) -> None:
        task = asyncio.current_task()
        if task is None:
            message = "Command admission requires an owning task"
            raise RuntimeError(message)

        def finish_task(_task: asyncio.Task[object]) -> None:
            self.finish(token)

        task.add_done_callback(finish_task)

    def finish(
        self,
        token: object,
        *,
        now: float | None = None,
    ) -> None:
        if not isinstance(token, CommandCooldownToken):
            return
        entry = self._entries.get((token.user_id, token.command_id))
        if entry is None or entry.active_token is not token or not entry.in_progress:
            return
        current_time = time.monotonic() if now is None else now
        entry.in_progress = False
        entry.active_token = None
        entry.completed_at.append(current_time)
        entry.feedback_sent = False

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
