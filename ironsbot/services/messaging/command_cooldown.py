# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Protocol

_ENTRY_PRUNE_INTERVAL_SECONDS = 60.0


class CommandCooldownConfig(Protocol):
    enabled: bool
    in_progress_message: str
    cooldown_message: str

    def seconds_for(self, command_id: str) -> float: ...


class SuperuserLookup(Protocol):
    def is_superuser(self, user_id: int) -> bool: ...


@dataclass(frozen=True, slots=True)
class CommandCooldownToken:
    user_id: int
    command_id: str
    cooldown_seconds: float


@dataclass(frozen=True, slots=True)
class CommandCooldownDecision:
    allowed: bool
    token: CommandCooldownToken | None = None
    feedback: str | None = None


@dataclass(slots=True)
class _CommandCooldownEntry:
    in_progress: bool = False
    cooldown_until: float = 0.0
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
        cooldown_seconds = self.config.seconds_for(command_id)
        if (
            not self.config.enabled
            or cooldown_seconds <= 0
            or self.features.is_superuser(user_id)
        ):
            return CommandCooldownDecision(allowed=True)

        current_time = time.monotonic() if now is None else now
        self._prune_expired(current_time)
        key = (user_id, command_id)
        entry = self._entries.get(key)
        if (
            entry is not None
            and not entry.in_progress
            and entry.cooldown_until <= current_time
        ):
            del self._entries[key]
            entry = None

        if entry is not None:
            feedback: str | None = None
            if not entry.feedback_sent:
                entry.feedback_sent = True
                feedback = (
                    self.config.in_progress_message
                    if entry.in_progress
                    else self.config.cooldown_message.format(
                        remaining_seconds=max(
                            1,
                            math.ceil(entry.cooldown_until - current_time),
                        )
                    )
                )
            return CommandCooldownDecision(allowed=False, feedback=feedback)

        self._entries[key] = _CommandCooldownEntry(in_progress=True)
        return CommandCooldownDecision(
            allowed=True,
            token=CommandCooldownToken(
                user_id,
                command_id,
                cooldown_seconds,
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
        entry.cooldown_until = current_time + token.cooldown_seconds

    def reset(self) -> None:
        self._entries.clear()
        self._last_prune_at = 0.0

    def _prune_expired(self, current_time: float) -> None:
        if current_time - self._last_prune_at < _ENTRY_PRUNE_INTERVAL_SECONDS:
            return
        self._last_prune_at = current_time
        self._entries = {
            key: entry
            for key, entry in self._entries.items()
            if entry.in_progress or entry.cooldown_until > current_time
        }
