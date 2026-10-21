# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import (
    MessageEvent,  # noqa: TC002 - NoneBot resolves it at runtime
)
from nonebot.log import logger
from nonebot.matcher import (
    Matcher,  # noqa: TC002 - NoneBot resolves handler annotations
)
from nonebot.message import run_postprocessor
from nonebot.plugin import on_command, on_fullmatch, on_message, on_notice
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves handler annotations

from ironsbot.integrations.onebot.replies import build_event_reply_message

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.core.action_categories import RequestCategory
    from ironsbot.core.command_catalog import CommandCatalog
    from ironsbot.integrations.onebot.matcher_contracts import (
        CommandCooldown,
        CommandIdSource,
        SemanticRequestResolver,
    )
    from ironsbot.runtime.in_flight_requests import (
        InFlightRequestService,
    )
from ironsbot.integrations.onebot.matcher_contracts import (
    CommandPolicyError,
    default_semantic_request,
    static_command_id,
)
from ironsbot.integrations.onebot.matcher_support import (
    EXPLICIT_COMMAND_STATE_KEY,
)
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.request_state import (
    COMMAND_COOLDOWN_TOKEN_STATE_KEY as _COMMAND_COOLDOWN_TOKEN_KEY,
)
from ironsbot.integrations.onebot.request_state import (
    IN_FLIGHT_REQUEST_TOKEN_STATE_KEY as _IN_FLIGHT_REQUEST_TOKEN_KEY,
)
from ironsbot.integrations.onebot.request_state import REQUEST_OUTCOME_STATE_KEY
from ironsbot.services.portable_reply import RequestOutcome

SEMANTIC_REQUEST_STATE_KEY = "_ironsbot_semantic_request"


@dataclass(frozen=True, slots=True)
class CommandPolicy:
    command_id: CommandIdSource | None = None
    exemption_reason: str | None = None
    semantic_request: SemanticRequestResolver | None = None
    help_ids: tuple[str, ...] = ()
    closes_active_conversation: bool = True
    category: RequestCategory | None = None

    def __post_init__(self) -> None:
        if (self.command_id is None) == (self.exemption_reason is None):
            raise CommandPolicyError.ambiguous()
        if self.exemption_reason is not None and not self.exemption_reason.strip():
            raise CommandPolicyError.empty_exemption()
        if self.exemption_reason is not None and (self.semantic_request is not None):
            raise CommandPolicyError.exempt_with_semantic_request()
        if self.exemption_reason is not None and self.help_ids:
            raise CommandPolicyError.exempt_with_help_ids()
        if self.exemption_reason is not None and self.closes_active_conversation:
            raise CommandPolicyError.exempt_with_conversation_close()
        if any(not command_id.strip() for command_id in self.help_ids):
            raise CommandPolicyError.empty_help_id()

    @classmethod
    def command(
        cls,
        command_id: CommandIdSource,
        *,
        semantic_request: SemanticRequestResolver | None = None,
        help_ids: tuple[str, ...] = (),
        closes_active_conversation: bool = True,
        category: RequestCategory | None = None,
    ) -> CommandPolicy:
        return cls(
            command_id=command_id,
            semantic_request=semantic_request,
            help_ids=help_ids,
            closes_active_conversation=closes_active_conversation,
            category=category,
        )

    @classmethod
    def exempt(cls, reason: str) -> CommandPolicy:
        return cls(exemption_reason=reason, closes_active_conversation=False)


def _command_policy_label(policy: CommandPolicy) -> str:
    command_id = policy.command_id
    if isinstance(command_id, str):
        return command_id
    if command_id is None:
        return "unknown"
    return getattr(command_id, "__name__", type(command_id).__name__)


@dataclass(slots=True)
class MatcherFactory:
    """Create and configure this application's OneBot matchers.

    The factory owns matcher construction-time policy only. It retains created
    matchers solely for command-catalog validation and startup smoke checks;
    it is not plugin discovery or a runtime service registry.
    """

    cooldown: CommandCooldown
    priorities: object
    in_flight_requests: InFlightRequestService | None = None
    close_portable_session: Callable[[MessageEvent], None] | None = None
    _message_matchers: list[type[Matcher]] = field(default_factory=list)
    _notice_matchers: list[type[Matcher]] = field(default_factory=list)
    _cooldown_registrations: dict[type[Matcher], tuple[str, str]] = field(
        default_factory=dict
    )
    _command_help_ids: set[str] = field(default_factory=set)
    _unclassified_command_labels: set[str] = field(default_factory=set)

    def on_message(
        self,
        *,
        policy: CommandPolicy,
        **kwargs: Any,
    ) -> type[Matcher]:
        return self._register_message(
            on_message(
                **self._with_runtime_hooks(
                    kwargs,
                    closes_active_conversation=policy.closes_active_conversation,
                )
            ),
            policy,
        )

    def on_fullmatch(
        self,
        msg: str | tuple[str, ...],
        *,
        policy: CommandPolicy,
        **kwargs: Any,
    ) -> type[Matcher]:
        return self._register_message(
            on_fullmatch(
                msg,
                **self._with_runtime_hooks(
                    kwargs,
                    closes_active_conversation=policy.closes_active_conversation,
                ),
            ),
            policy,
        )

    def on_command(
        self,
        cmd: str | tuple[str, ...],
        *,
        policy: CommandPolicy,
        **kwargs: Any,
    ) -> type[Matcher]:
        return self._register_message(
            on_command(
                cmd,
                **self._with_runtime_hooks(
                    kwargs,
                    closes_active_conversation=policy.closes_active_conversation,
                ),
            ),
            policy,
        )

    def on_notice(self, **kwargs: Any) -> type[Matcher]:
        matcher = on_notice(**self._with_runtime_hooks(kwargs))
        self._notice_matchers.append(matcher)
        return matcher

    def install_postprocessor(self) -> None:
        @run_postprocessor
        async def finalize(state: T_State, exception: Exception | None = None) -> None:
            outcome = state.pop(REQUEST_OUTCOME_STATE_KEY, None)
            failed = exception is not None or (
                isinstance(outcome, RequestOutcome) and outcome.failed
            )
            for service, key in (
                (self.in_flight_requests, _IN_FLIGHT_REQUEST_TOKEN_KEY),
                (self.cooldown, _COMMAND_COOLDOWN_TOKEN_KEY),
            ):
                token = state.pop(key, None)
                if token is not None and service is not None:
                    if failed:
                        service.release(token)
                    else:
                        service.finish(token)

    def priority(self, name: str) -> int:
        return int(getattr(self.priorities, name))

    def pre_command_priority(self, name: str) -> int:
        return min(self.priority(name), -1)

    @property
    def message_matchers(self) -> tuple[type[Matcher], ...]:
        return tuple(self._message_matchers)

    @property
    def notice_matchers(self) -> tuple[type[Matcher], ...]:
        return tuple(self._notice_matchers)

    def cooldown_registration(
        self,
        matcher: type[Matcher],
    ) -> tuple[str, str] | None:
        return self._cooldown_registrations.get(matcher)

    def validate_command_catalog(self, catalog: CommandCatalog) -> None:
        catalog.validate_matcher_registrations(
            help_ids=self._command_help_ids,
            unclassified_labels=self._unclassified_command_labels,
        )

    def _register_message(
        self,
        matcher: type[Matcher],
        policy: CommandPolicy,
    ) -> type[Matcher]:
        if policy.command_id is not None:
            self._install_admission(matcher, policy)
            if policy.help_ids:
                self._command_help_ids.update(policy.help_ids)
            else:
                self._unclassified_command_labels.add(_command_policy_label(policy))
        else:
            self._cooldown_registrations[matcher] = (
                "exempt",
                policy.exemption_reason or "",
            )
        self._message_matchers.append(matcher)
        return matcher

    def _install_admission(  # noqa: C901
        self,
        matcher: type[Matcher],
        policy: CommandPolicy,
    ) -> None:
        command_id = policy.command_id
        if command_id is None:
            return
        resolver = (
            static_command_id(command_id) if isinstance(command_id, str) else command_id
        )
        label = (
            command_id
            if isinstance(command_id, str)
            else getattr(resolver, "__name__", type(resolver).__name__)
        )

        async def admit(  # noqa: C901
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

            request = (
                policy.semantic_request(event, state)
                if policy.semantic_request is not None
                else default_semantic_request(
                    command_id=normalized_id,
                    label=str(label),
                    event=event,
                    state=state,
                    category=policy.category,
                )
            )
            if request is not None:
                state[SEMANTIC_REQUEST_STATE_KEY] = request
                if self.in_flight_requests is not None:
                    request_decision = self.in_flight_requests.admit(
                        actor=message_input_context(event).message.actor,
                        conversation=message_input_context(event).message.conversation,
                        request=request,
                        bot_id=str(event.self_id),
                    )
                    if request_decision.token is not None:
                        state[_IN_FLIGHT_REQUEST_TOKEN_KEY] = request_decision.token
                    if not request_decision.allowed:
                        await matcher.finish(
                            build_event_reply_message(event, request_decision.feedback)
                            if request_decision.feedback is not None
                            else None
                        )

            decision = self.cooldown.admit(
                actor=message_input_context(event).message.actor,
                command_id=normalized_id,
            )
            if not decision.allowed:
                request_token = state.pop(_IN_FLIGHT_REQUEST_TOKEN_KEY, None)
                if request_token is not None and self.in_flight_requests is not None:
                    self.in_flight_requests.release(request_token)
            if decision.token is not None:
                state[_COMMAND_COOLDOWN_TOKEN_KEY] = decision.token
            if not decision.allowed:
                await matcher.finish(
                    build_event_reply_message(event, decision.feedback)
                    if decision.feedback is not None
                    else None
                )
            if policy.closes_active_conversation and self.close_portable_session:
                self.close_portable_session(event)

        dependent = matcher.append_handler(admit)
        matcher.handlers.remove(dependent)
        matcher.handlers.insert(0, dependent)
        self._cooldown_registrations[matcher] = ("command", str(label))

    def _with_runtime_hooks(
        self,
        kwargs: dict[str, Any],
        *,
        closes_active_conversation: bool = False,
    ) -> dict[str, Any]:
        if not closes_active_conversation:
            return kwargs
        updated = dict(kwargs)
        state = dict(updated.get("state") or {})
        state[EXPLICIT_COMMAND_STATE_KEY] = True
        updated["state"] = state
        return updated
