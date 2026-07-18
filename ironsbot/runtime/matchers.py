# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nonebot.plugin import on_command, on_fullmatch, on_message, on_notice

from ironsbot.shared.messaging.command_cooldown import (
    CommandIdSource,
    install_command_cooldown_postprocessor,
    mark_command_matcher_exempt,
    register_command_matcher,
    validate_command_matcher_coverage,
)

if TYPE_CHECKING:
    from nonebot.matcher import Matcher


class CommandPolicyError(ValueError):
    @classmethod
    def ambiguous(cls) -> CommandPolicyError:
        return cls("command policy requires exactly one command id or exemption")

    @classmethod
    def empty_exemption(cls) -> CommandPolicyError:
        return cls("command policy exemption reason must not be empty")


@dataclass(frozen=True, slots=True)
class CommandPolicy:
    command_id: CommandIdSource | None = None
    exemption_reason: str | None = None

    def __post_init__(self) -> None:
        if (self.command_id is None) == (self.exemption_reason is None):
            raise CommandPolicyError.ambiguous()
        if self.exemption_reason is not None and not self.exemption_reason.strip():
            raise CommandPolicyError.empty_exemption()

    @classmethod
    def command(cls, command_id: CommandIdSource) -> CommandPolicy:
        return cls(command_id=command_id)

    @classmethod
    def exempt(cls, reason: str) -> CommandPolicy:
        return cls(exemption_reason=reason)


@dataclass(slots=True)
class MatcherRegistry:
    _message_matchers: list[type[Matcher]] = field(default_factory=list)
    _notice_matchers: list[type[Matcher]] = field(default_factory=list)

    def on_message(
        self,
        *,
        policy: CommandPolicy,
        **kwargs: Any,
    ) -> type[Matcher]:
        return self._register_message(on_message(**kwargs), policy)

    def on_fullmatch(
        self,
        msg: str | tuple[str, ...],
        *,
        policy: CommandPolicy,
        **kwargs: Any,
    ) -> type[Matcher]:
        return self._register_message(on_fullmatch(msg, **kwargs), policy)

    def on_command(
        self,
        cmd: str | tuple[str, ...],
        *,
        policy: CommandPolicy,
        **kwargs: Any,
    ) -> type[Matcher]:
        return self._register_message(on_command(cmd, **kwargs), policy)

    def on_notice(self, **kwargs: Any) -> type[Matcher]:
        matcher = on_notice(**kwargs)
        self._notice_matchers.append(matcher)
        return matcher

    def install_postprocessor(self) -> None:
        registered = frozenset(self._message_matchers)
        validate_command_matcher_coverage(lambda matcher: matcher in registered)
        install_command_cooldown_postprocessor(
            lambda matcher: matcher in registered
        )

    @property
    def message_matchers(self) -> tuple[type[Matcher], ...]:
        return tuple(self._message_matchers)

    @property
    def notice_matchers(self) -> tuple[type[Matcher], ...]:
        return tuple(self._notice_matchers)

    def _register_message(
        self,
        matcher: type[Matcher],
        policy: CommandPolicy,
    ) -> type[Matcher]:
        if policy.command_id is not None:
            register_command_matcher(matcher, policy.command_id)
        else:
            mark_command_matcher_exempt(
                matcher,
                policy.exemption_reason or "",
            )
        self._message_matchers.append(matcher)
        return matcher


__all__ = ["CommandPolicy", "CommandPolicyError", "MatcherRegistry"]
