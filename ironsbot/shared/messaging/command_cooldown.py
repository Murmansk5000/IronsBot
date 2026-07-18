# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.log import logger
from nonebot.message import run_postprocessor
from nonebot.typing import T_State

from .text import build_message

if TYPE_CHECKING:
    from nonebot.matcher import Matcher

    from ironsbot.config.models.runtime import CommandCooldownConfig
    from ironsbot.shared.features import FeatureService

CommandIdResolver = Callable[[MessageEvent, T_State], str | None]
CommandIdSource = str | CommandIdResolver

_COMMAND_COOLDOWN_TOKEN_KEY = "_ironsbot_command_cooldown_token"  # nosec B105
_ENTRY_PRUNE_INTERVAL_SECONDS = 60.0


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


class CommandCooldownRegistrationError(ValueError):
    @classmethod
    def duplicate(cls, matcher: type[Matcher]) -> CommandCooldownRegistrationError:
        return cls(f"matcher already has command cooldown policy: {matcher}")

    @classmethod
    def empty_reason(cls) -> CommandCooldownRegistrationError:
        return cls("command cooldown exemption reason must not be empty")


@dataclass(slots=True)
class CommandCooldownService:
    config: CommandCooldownConfig
    features: FeatureService
    _entries: dict[tuple[int, str], _CommandCooldownEntry] = field(
        default_factory=dict
    )
    _registrations: dict[type[Matcher], tuple[str, str]] = field(
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
        token: CommandCooldownToken,
        *,
        now: float | None = None,
    ) -> None:
        entry = self._entries.get((token.user_id, token.command_id))
        if entry is None or not entry.in_progress:
            return
        current_time = time.monotonic() if now is None else now
        entry.in_progress = False
        entry.cooldown_until = current_time + token.cooldown_seconds

    def register_matcher(
        self,
        matcher: type[Matcher],
        command_id: CommandIdSource,
    ) -> None:
        self._ensure_unregistered(matcher)
        resolver = (
            _static_command_id(command_id)
            if isinstance(command_id, str)
            else command_id
        )
        label = (
            command_id
            if isinstance(command_id, str)
            else getattr(resolver, "__name__", type(resolver).__name__)
        )

        async def admit(
            matcher: Matcher,
            event: MessageEvent,
            state: T_State,
        ) -> None:
            resolved_id = resolver(event, state)
            if resolved_id is None:
                return
            normalized_id = resolved_id.strip()
            if not normalized_id:
                logger.warning("command cooldown resolver returned an empty command id")
                return

            decision = self.admit(
                user_id=event.user_id,
                command_id=normalized_id,
            )
            if decision.token is not None:
                state[_COMMAND_COOLDOWN_TOKEN_KEY] = decision.token
            if decision.allowed:
                return
            await matcher.finish(
                build_message(decision.feedback)
                if decision.feedback is not None
                else None
            )

        dependent = matcher.append_handler(admit)
        matcher.handlers.remove(dependent)
        matcher.handlers.insert(0, dependent)
        self._registrations[matcher] = ("command", str(label))

    def exempt_matcher(self, matcher: type[Matcher], reason: str) -> None:
        self._ensure_unregistered(matcher)
        normalized = reason.strip()
        if not normalized:
            raise CommandCooldownRegistrationError.empty_reason()
        self._registrations[matcher] = ("exempt", normalized)

    def registration(self, matcher: type[Matcher]) -> tuple[str, str] | None:
        return self._registrations.get(matcher)

    def install_postprocessor(self) -> None:
        @run_postprocessor
        async def finalize(state: T_State) -> None:
            token = state.pop(_COMMAND_COOLDOWN_TOKEN_KEY, None)
            if isinstance(token, CommandCooldownToken):
                self.finish(token)

    def reset(self) -> None:
        self._entries.clear()
        self._last_prune_at = 0.0

    def _ensure_unregistered(self, matcher: type[Matcher]) -> None:
        if matcher in self._registrations:
            raise CommandCooldownRegistrationError.duplicate(matcher)

    def _prune_expired(self, current_time: float) -> None:
        if current_time - self._last_prune_at < _ENTRY_PRUNE_INTERVAL_SECONDS:
            return
        self._last_prune_at = current_time
        self._entries = {
            key: entry
            for key, entry in self._entries.items()
            if entry.in_progress or entry.cooldown_until > current_time
        }


def _static_command_id(command_id: str) -> CommandIdResolver:
    def resolve(_event: MessageEvent, _state: T_State) -> str:
        return command_id

    return resolve
