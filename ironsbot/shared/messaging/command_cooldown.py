# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.log import logger
from nonebot.matcher import Matcher, matchers
from nonebot.message import run_postprocessor
from nonebot.typing import T_State

from ironsbot.config.loader import get_app_config
from ironsbot.shared.features import is_superuser

from .text import build_message

CommandIdResolver = Callable[[MessageEvent, T_State], str | None]
CommandIdSource = str | CommandIdResolver
MatcherFilter = Callable[[type[Matcher]], bool]

_COMMAND_COOLDOWN_TOKEN_KEY = "_ironsbot_command_cooldown_token"
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
        return cls(f"matcher already has command cooldown: {matcher}")

    @classmethod
    def exempt(cls, matcher: type[Matcher]) -> CommandCooldownRegistrationError:
        return cls(f"matcher is marked command cooldown exempt: {matcher}")

    @classmethod
    def empty_reason(cls) -> CommandCooldownRegistrationError:
        return cls("command cooldown exemption reason must not be empty")

    @classmethod
    def uncovered(
        cls,
        matcher_names: list[str],
    ) -> CommandCooldownRegistrationError:
        return cls(
            "message matchers must register a semantic command id or exemption: "
            + ", ".join(matcher_names)
        )


@dataclass(slots=True)
class CommandCooldownService:
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
        config = get_app_config().runtime.command_cooldown
        cooldown_seconds = config.seconds_for(command_id)
        if (
            not config.enabled
            or cooldown_seconds <= 0
            or is_superuser(user_id)
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
                if entry.in_progress:
                    feedback = config.in_progress_message
                else:
                    remaining = max(
                        1,
                        math.ceil(entry.cooldown_until - current_time),
                    )
                    feedback = config.cooldown_message.format(
                        remaining_seconds=remaining
                    )
            return CommandCooldownDecision(
                allowed=False,
                feedback=feedback,
            )

        self._entries[key] = _CommandCooldownEntry(in_progress=True)
        return CommandCooldownDecision(
            allowed=True,
            token=CommandCooldownToken(
                user_id=user_id,
                command_id=command_id,
                cooldown_seconds=cooldown_seconds,
            ),
        )

    def finish(
        self,
        token: CommandCooldownToken,
        *,
        now: float | None = None,
    ) -> None:
        key = (token.user_id, token.command_id)
        entry = self._entries.get(key)
        if entry is None or not entry.in_progress:
            return

        current_time = time.monotonic() if now is None else now
        entry.in_progress = False
        entry.cooldown_until = current_time + token.cooldown_seconds

    def reset(self) -> None:
        self._entries.clear()
        self._last_prune_at = 0.0

    def _prune_expired(self, current_time: float) -> None:
        if (
            current_time - self._last_prune_at
            < _ENTRY_PRUNE_INTERVAL_SECONDS
        ):
            return
        self._last_prune_at = current_time
        self._entries = {
            key: entry
            for key, entry in self._entries.items()
            if entry.in_progress or entry.cooldown_until > current_time
        }


command_cooldown_service = CommandCooldownService()
_registered_matchers: dict[type[Matcher], str] = {}
_exempt_matchers: dict[type[Matcher], str] = {}
_runtime_registered = False


def _resolve_static_command_id(command_id: str) -> CommandIdResolver:
    def _resolver(_event: MessageEvent, _state: T_State) -> str:
        return command_id

    return _resolver


def register_command_matcher(
    matcher: type[Matcher],
    command_id: CommandIdSource,
) -> None:
    if matcher in _registered_matchers:
        raise CommandCooldownRegistrationError.duplicate(matcher)
    if matcher in _exempt_matchers:
        raise CommandCooldownRegistrationError.exempt(matcher)

    resolver = (
        _resolve_static_command_id(command_id)
        if isinstance(command_id, str)
        else command_id
    )
    label = command_id if isinstance(command_id, str) else resolver.__name__

    async def _command_cooldown_admission(
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

        decision = command_cooldown_service.admit(
            user_id=event.user_id,
            command_id=normalized_id,
        )
        if decision.token is not None:
            state[_COMMAND_COOLDOWN_TOKEN_KEY] = decision.token
        if decision.allowed:
            return

        if decision.feedback is None:
            await matcher.finish()
        await matcher.finish(build_message(decision.feedback))

    dependent = matcher.append_handler(_command_cooldown_admission)
    matcher.handlers.remove(dependent)
    matcher.handlers.insert(0, dependent)
    _registered_matchers[matcher] = str(label)


def mark_command_matcher_exempt(
    matcher: type[Matcher],
    reason: str,
) -> None:
    if matcher in _registered_matchers:
        raise CommandCooldownRegistrationError.duplicate(matcher)
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise CommandCooldownRegistrationError.empty_reason()
    _exempt_matchers[matcher] = normalized_reason


def command_matcher_registration(
    matcher: type[Matcher],
) -> tuple[str, str] | None:
    if matcher in _registered_matchers:
        return ("command", _registered_matchers[matcher])
    if matcher in _exempt_matchers:
        return ("exempt", _exempt_matchers[matcher])
    return None


def find_unregistered_message_matchers(
    matcher_filter: MatcherFilter | None = None,
) -> list[type[Matcher]]:
    uncovered: list[type[Matcher]] = []
    for priority_matchers in matchers.values():
        for matcher in priority_matchers:
            if (
                matcher.type != "message"
                or matcher.temp
                or (
                    matcher_filter is not None
                    and not matcher_filter(matcher)
                )
                or command_matcher_registration(matcher) is not None
            ):
                continue
            uncovered.append(matcher)
    return uncovered


def validate_command_matcher_coverage(
    matcher_filter: MatcherFilter | None = None,
) -> None:
    uncovered = find_unregistered_message_matchers(matcher_filter)
    if not uncovered:
        return
    raise CommandCooldownRegistrationError.uncovered(
        [str(matcher) for matcher in uncovered]
    )


def reset_command_cooldown_state() -> None:
    command_cooldown_service.reset()


async def finalize_command_cooldown_state(state: T_State) -> None:
    token = state.pop(_COMMAND_COOLDOWN_TOKEN_KEY, None)
    if isinstance(token, CommandCooldownToken):
        command_cooldown_service.finish(token)


def setup_command_cooldown_runtime(
    matcher_filter: MatcherFilter | None = None,
) -> None:
    global _runtime_registered  # noqa: PLW0603

    if _runtime_registered:
        return
    validate_command_matcher_coverage(matcher_filter)

    @run_postprocessor
    async def _finish_command_cooldown(state: T_State) -> None:
        await finalize_command_cooldown_state(state)

    _runtime_registered = True


__all__ = [
    "CommandCooldownDecision",
    "CommandCooldownService",
    "CommandCooldownToken",
    "CommandIdResolver",
    "CommandIdSource",
    "MatcherFilter",
    "command_matcher_registration",
    "finalize_command_cooldown_state",
    "find_unregistered_message_matchers",
    "mark_command_matcher_exempt",
    "register_command_matcher",
    "reset_command_cooldown_state",
    "setup_command_cooldown_runtime",
    "validate_command_matcher_coverage",
]
