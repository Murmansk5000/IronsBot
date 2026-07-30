# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from functools import partial
from inspect import Signature, signature
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any, TypeAlias, TypeVar, cast

from nonebot.adapters import Event, Message, MessageSegment, MessageTemplate
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.adapters.onebot.v11 import MessageSegment as OneBotMessageSegment
from nonebot.consts import REJECT_CACHE_TARGET, REJECT_TARGET
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.matcher import Matcher, current_bot, current_event, current_handler
from nonebot.message import run_postprocessor
from nonebot.plugin import on_command, on_fullmatch, on_message, on_notice
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves handler annotations

if TYPE_CHECKING:
    from ironsbot.runtime.commands import CommandCatalog
    from ironsbot.runtime.in_flight_requests import (
        InFlightRequestService,
    )
    from ironsbot.runtime.matcher_contracts import (
        CommandCooldown,
        CommandIdSource,
        QueuedSemanticRequestResolver,
        SemanticRequestResolver,
    )
    from ironsbot.runtime.prompt_sessions import _QueuedConversation
from ironsbot.runtime.matcher_contracts import (
    CommandPolicyError,
    static_command_id,
)
from ironsbot.runtime.prompt_errors import (
    PromptLoopConfigurationError,
    PromptSessionManagerMissingError,
)
from ironsbot.runtime.prompt_sessions import (
    COMMAND_COOLDOWN_TOKEN_STATE_KEY as _COMMAND_COOLDOWN_TOKEN_KEY,
)
from ironsbot.runtime.prompt_sessions import (
    IN_FLIGHT_REQUEST_TOKEN_STATE_KEY as _IN_FLIGHT_REQUEST_TOKEN_KEY,
)
from ironsbot.runtime.prompt_sessions import (
    QUEUED_CONVERSATION_TICKET_STATE_KEY,
    QUEUED_CONVERSATION_TOKEN_STATE_KEY,
    TEMP_MATCHER_STATE_TOKEN_KEY,
    PromptSessionManager,
)
from ironsbot.runtime.semantic_requests import (
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    normalized_text_target,
)

ReplyBeforeSend = Callable[[Event | None], Awaitable[None]]
RUNTIME_CONTEXT_TOKEN_STATE_KEY = "_ironsbot_runtime_context_token"
SEMANTIC_REQUEST_STATE_KEY = "_ironsbot_semantic_request"
T_Message: TypeAlias = str | Message | MessageSegment | MessageTemplate
T = TypeVar("T")


class _BoundPartial(partial):
    @property
    def __globals__(self) -> dict[str, Any]:
        """Expose the wrapped function globals for NoneBot dependency parsing."""

        return cast("dict[str, Any]", getattr(self.func, "__globals__", {}))

    @property
    def __signature__(self) -> Signature:
        """Hide arguments already supplied by the application runtime."""

        original = signature(self.func)
        try:
            supplied = original.bind_partial(*self.args, **(self.keywords or {}))
        except TypeError:
            return original
        return original.replace(
            parameters=[
                parameter
                for name, parameter in original.parameters.items()
                if name not in supplied.arguments
            ]
        )


class _AsyncPartial(_BoundPartial):
    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        result: Awaitable[Any] = super().__call__(*args, **kwargs)
        return await result


def bind(
    func: Callable[..., T],
    /,
    *args: Any,
    **kwargs: Any,
) -> Callable[..., T]:
    """Bind a synchronous NoneBot callback without hiding its annotations."""

    return cast("Callable[..., T]", _BoundPartial(func, *args, **kwargs))


def bind_async(
    func: Callable[..., Awaitable[T]],
    /,
    *args: Any,
    **kwargs: Any,
) -> Callable[..., Awaitable[T]]:
    """Bind arguments while keeping the callable visibly asynchronous."""

    return cast(
        "Callable[..., Awaitable[T]]",
        _AsyncPartial(func, *args, **kwargs),
    )


@dataclass(frozen=True, slots=True)
class _MatcherRuntimeContext:
    before_reply_send: ReplyBeforeSend | None
    prompt_session_manager: PromptSessionManager | None
    in_flight_requests: InFlightRequestService | None


_MATCHER_RUNTIME_CONTEXTS: dict[str, _MatcherRuntimeContext] = {}


def _runtime_context(
    source: Matcher | dict[Any, Any],
) -> _MatcherRuntimeContext | None:
    state = source if isinstance(source, dict) else source.state
    token = state.get(RUNTIME_CONTEXT_TOKEN_STATE_KEY)
    if not isinstance(token, str):
        return None
    return _MATCHER_RUNTIME_CONTEXTS.get(token)


def get_prompt_session_manager(
    source: Matcher | dict[Any, Any],
) -> PromptSessionManager:
    context = _runtime_context(source)
    manager = None if context is None else context.prompt_session_manager
    if not isinstance(manager, PromptSessionManager):
        raise PromptSessionManagerMissingError
    return manager


def get_reply_before_send(
    source: Matcher | dict[Any, Any],
) -> ReplyBeforeSend | None:
    return (
        None
        if (context := _runtime_context(source)) is None
        else context.before_reply_send
    )


def get_queued_conversation(
    source: Matcher | dict[Any, Any],
) -> _QueuedConversation | None:
    try:
        return get_prompt_session_manager(source).queued_conversation(
            source if isinstance(source, dict) else source.state
        )
    except PromptSessionManagerMissingError:
        return None


def queued_conversation_is_cancelled(
    source: Matcher | dict[Any, Any],
) -> bool:
    state = source if isinstance(source, dict) else source.state
    try:
        return get_prompt_session_manager(source).queued_conversation_is_cancelled(
            state
        )
    except PromptSessionManagerMissingError:
        return False


def update_queued_reply_check(
    matcher: Matcher,
    reply_check: Callable[[Event], bool],
) -> None:
    context = get_queued_conversation(matcher)
    if context is not None:
        context.update_reply_check(reply_check)


async def reject_with_rule(
    matcher: Matcher,
    rule: Rule,
    prompt: T_Message | None = None,
    **kwargs: Any,
) -> None:
    if queued_conversation_is_cancelled(matcher):
        raise FinishedException
    if prompt is not None:
        await matcher.send(prompt, **kwargs)

    if context := get_queued_conversation(matcher):
        context.keep_open = True
        raise FinishedException

    matcher.remain_handlers.insert(0, current_handler.get())
    if REJECT_CACHE_TARGET in matcher.state:
        matcher.state[REJECT_TARGET] = matcher.state[REJECT_CACHE_TARGET]
    await _create_temp_matcher(matcher, rule)
    raise FinishedException


async def enter_prompt_loop(  # noqa: PLR0913
    matcher: Matcher,
    handlers: list[Any],
    rule: Rule,
    prompt: T_Message | None = None,
    *,
    queue_namespace: str | None = None,
    queue_reply_check: Callable[[Event], bool] | None = None,
    queue_semantic_request_resolver: QueuedSemanticRequestResolver | None = None,
    **kwargs: Any,
) -> None:
    if queued_conversation_is_cancelled(matcher):
        raise FinishedException
    if prompt is not None:
        await matcher.send(prompt, **kwargs)
    if queue_namespace is not None:
        if queue_reply_check is None:
            raise PromptLoopConfigurationError
        if context := get_queued_conversation(matcher):
            if context.namespace == queue_namespace:
                context.update_reply_check(queue_reply_check)
                context.update_semantic_request_resolver(
                    queue_semantic_request_resolver
                )
                context.keep_open = True
                raise FinishedException
            get_prompt_session_manager(matcher).cancel_queued_conversation(
                matcher.state
            )
            matcher.state.pop(QUEUED_CONVERSATION_TOKEN_STATE_KEY, None)
            matcher.state.pop(QUEUED_CONVERSATION_TICKET_STATE_KEY, None)
        event = current_event.get()
        prompt_sessions = get_prompt_session_manager(matcher)
        runtime_context = _runtime_context(matcher)
        queued = prompt_sessions.start_queued_conversation(
            namespace=queue_namespace,
            event_session_id=event.get_session_id(),
            state=matcher.state,
            reply_check=queue_reply_check,
            handlers=handlers,
            semantic_request_resolver=queue_semantic_request_resolver,
            request_service=(
                None
                if runtime_context is None
                else runtime_context.in_flight_requests
            ),
        )
        await _create_queued_temp_matcher(matcher, queued)
        raise FinishedException
    await _create_temp_matcher(matcher, rule, handlers=handlers)
    raise FinishedException


async def _create_temp_matcher(
    matcher: Matcher,
    rule: Rule,
    *,
    handlers: list[Any] | None = None,
) -> None:
    bot = current_bot.get()
    event = current_event.get()
    permission = await matcher.update_permission(bot, event)
    token = PromptSessionManager.store_temporary_matcher_state(
        matcher.state,
        expires_after=bot.config.session_expire_timeout,
    )
    temporary_handlers = [
        _restore_temporary_matcher_state,
        *(handlers if handlers is not None else matcher.remain_handlers),
    ]
    matcher.__class__.new(
        "message",
        rule,
        permission,
        temporary_handlers,
        temp=True,
        priority=0,
        block=True,
        source=matcher.__class__._source,
        expire_time=bot.config.session_expire_timeout,
        default_state={TEMP_MATCHER_STATE_TOKEN_KEY: token},
        default_type_updater=matcher.__class__._default_type_updater,
        default_permission_updater=matcher.__class__._default_permission_updater,
    )


async def _create_queued_temp_matcher(
    matcher: Matcher,
    context: _QueuedConversation,
) -> None:
    bot = current_bot.get()
    event = current_event.get()
    permission = await matcher.update_permission(bot, event)
    get_prompt_session_manager(matcher).refresh_queued_conversation_expiry(
        context,
        expires_after=bot.config.session_expire_timeout,
    )
    default_state: T_State = {
        QUEUED_CONVERSATION_TOKEN_STATE_KEY: context.token,
    }
    if runtime_token := matcher.state.get(RUNTIME_CONTEXT_TOKEN_STATE_KEY):
        default_state[RUNTIME_CONTEXT_TOKEN_STATE_KEY] = runtime_token
    matcher.__class__.new(
        "message",
        Rule(context.matches),
        permission,
        [_capture_queued_conversation_input, *context.handlers],
        temp=True,
        priority=0,
        block=True,
        source=matcher.__class__._source,
        expire_time=bot.config.session_expire_timeout,
        default_state=default_state,
        default_type_updater=matcher.__class__._default_type_updater,
        default_permission_updater=matcher.__class__._default_permission_updater,
    )


async def _capture_queued_conversation_input(  # noqa: C901
    matcher: Matcher,
    event: Event,
    _state: T_State,
) -> None:
    context = get_queued_conversation(_state)
    if context is None or not context.active:
        raise FinishedException

    if not isinstance(event, MessageEvent):
        raise FinishedException

    if event.get_plaintext().strip() == "0":
        get_prompt_session_manager(_state).cancel_queued_conversation(_state)
        if getattr(event, "group_id", None) is not None:
            await matcher.finish(
                OneBotMessageSegment.at(event.user_id)
                + OneBotMessageSegment.text(" 已退出当前选择。")
            )
        await matcher.finish("已退出当前选择。")

    request_token: object | None = None
    if context.semantic_request_resolver is not None:
        request = context.semantic_request_resolver(event, context.state)
        request_service = context.request_service
        if request is not None and request_service is not None:
            decision = request_service.admit(
                user_id=event.user_id,
                request=request,
            )
            if not decision.allowed:
                await _create_queued_temp_matcher(matcher, context)
                context.keep_open = True
                if decision.feedback is not None:
                    await _send_in_flight_feedback(matcher, event, decision.feedback)
                raise FinishedException
            request_token = decision.token

    await _create_queued_temp_matcher(matcher, context)
    try:
        ticket = await context.acquire(request_token)
    except BaseException:
        if request_token is not None and context.request_service is not None:
            context.request_service.release(request_token)
        raise
    if ticket is None:
        raise FinishedException
    _state.clear()
    _state.update(context.state)
    _state[QUEUED_CONVERSATION_TOKEN_STATE_KEY] = context.token
    _state[QUEUED_CONVERSATION_TICKET_STATE_KEY] = ticket
    if request_token is not None:
        _state[_IN_FLIGHT_REQUEST_TOKEN_KEY] = request_token


async def _send_in_flight_feedback(
    matcher: Matcher,
    event: MessageEvent,
    feedback: str,
) -> None:
    if getattr(event, "group_id", None) is not None:
        await matcher.send(
            OneBotMessageSegment.at(event.user_id)
            + OneBotMessageSegment.text(f" {feedback}")
        )
        return
    await matcher.send(feedback)


async def _restore_temporary_matcher_state(state: T_State) -> None:
    token = state.pop(TEMP_MATCHER_STATE_TOKEN_KEY, None)
    if not isinstance(token, str):
        raise FinishedException

    saved_state = PromptSessionManager.take_temporary_matcher_state(token)
    if saved_state is None:
        raise FinishedException

    incoming_state = dict(state)
    state.clear()
    state.update(saved_state)
    state.update(incoming_state)


@dataclass(frozen=True, slots=True)
class CommandPolicy:
    command_id: CommandIdSource | None = None
    exemption_reason: str | None = None
    semantic_request: SemanticRequestResolver | None = None
    help_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (self.command_id is None) == (self.exemption_reason is None):
            raise CommandPolicyError.ambiguous()
        if self.exemption_reason is not None and not self.exemption_reason.strip():
            raise CommandPolicyError.empty_exemption()
        if self.exemption_reason is not None and (
            self.semantic_request is not None
        ):
            raise CommandPolicyError.exempt_with_semantic_request()
        if self.exemption_reason is not None and self.help_ids:
            raise CommandPolicyError.exempt_with_help_ids()
        if any(not command_id.strip() for command_id in self.help_ids):
            raise CommandPolicyError.empty_help_id()

    @classmethod
    def command(
        cls,
        command_id: CommandIdSource,
        *,
        semantic_request: SemanticRequestResolver | None = None,
        help_ids: tuple[str, ...] = (),
    ) -> CommandPolicy:
        return cls(
            command_id=command_id,
            semantic_request=semantic_request,
            help_ids=help_ids,
        )

    @classmethod
    def exempt(cls, reason: str) -> CommandPolicy:
        return cls(exemption_reason=reason)


def _command_policy_label(policy: CommandPolicy) -> str:
    command_id = policy.command_id
    if isinstance(command_id, str):
        return command_id
    if command_id is None:
        return "unknown"
    return getattr(command_id, "__name__", type(command_id).__name__)


@dataclass(slots=True)
class MatcherRegistry:
    cooldown: CommandCooldown
    priorities: object
    before_reply_send: ReplyBeforeSend | None = None
    prompt_session_manager: PromptSessionManager | None = None
    in_flight_requests: InFlightRequestService | None = None
    _message_matchers: list[type[Matcher]] = field(default_factory=list)
    _notice_matchers: list[type[Matcher]] = field(default_factory=list)
    _cooldown_registrations: dict[type[Matcher], tuple[str, str]] = field(
        default_factory=dict
    )
    _command_help_ids: set[str] = field(default_factory=set)
    _unclassified_command_labels: set[str] = field(default_factory=set)
    _runtime_context_token: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            self.before_reply_send is None
            and self.prompt_session_manager is None
            and self.in_flight_requests is None
        ):
            return
        token = token_urlsafe(18)
        _MATCHER_RUNTIME_CONTEXTS[token] = _MatcherRuntimeContext(
            before_reply_send=self.before_reply_send,
            prompt_session_manager=self.prompt_session_manager,
            in_flight_requests=self.in_flight_requests,
        )
        self._runtime_context_token = token

    def on_message(
        self,
        *,
        policy: CommandPolicy,
        **kwargs: Any,
    ) -> type[Matcher]:
        return self._register_message(
            on_message(**self._with_runtime_hooks(kwargs)),
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
            on_fullmatch(msg, **self._with_runtime_hooks(kwargs)),
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
            on_command(cmd, **self._with_runtime_hooks(kwargs)),
            policy,
        )

    def on_notice(self, **kwargs: Any) -> type[Matcher]:
        matcher = on_notice(**self._with_runtime_hooks(kwargs))
        self._notice_matchers.append(matcher)
        return matcher

    def install_postprocessor(self) -> None:
        @run_postprocessor
        async def finalize(state: T_State) -> None:
            with suppress(PromptSessionManagerMissingError):
                get_prompt_session_manager(state).finish_queued_conversation(state)
            token = state.pop(_IN_FLIGHT_REQUEST_TOKEN_KEY, None)
            if token is not None and self.in_flight_requests is not None:
                self.in_flight_requests.finish(token)
            token = state.pop(_COMMAND_COOLDOWN_TOKEN_KEY, None)
            if token is not None:
                self.cooldown.finish(token)

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
            static_command_id(command_id)
            if isinstance(command_id, str)
            else command_id
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
                else _default_semantic_request(
                    command_id=normalized_id,
                    label=str(label),
                    event=event,
                    _state=state,
                )
            )
            if request is not None:
                state[SEMANTIC_REQUEST_STATE_KEY] = request
                if self.in_flight_requests is not None:
                    request_decision = self.in_flight_requests.admit(
                        user_id=event.user_id,
                        request=request,
                    )
                    if request_decision.token is not None:
                        state[_IN_FLIGHT_REQUEST_TOKEN_KEY] = request_decision.token
                    if not request_decision.allowed:
                        await matcher.finish(request_decision.feedback)

            decision = self.cooldown.admit(
                user_id=event.user_id,
                command_id=normalized_id,
            )
            if not decision.allowed:
                request_token = state.pop(_IN_FLIGHT_REQUEST_TOKEN_KEY, None)
                if request_token is not None and self.in_flight_requests is not None:
                    self.in_flight_requests.release(request_token)
            if decision.token is not None:
                state[_COMMAND_COOLDOWN_TOKEN_KEY] = decision.token
            if not decision.allowed:
                await matcher.finish(decision.feedback)

        dependent = matcher.append_handler(admit)
        matcher.handlers.remove(dependent)
        matcher.handlers.insert(0, dependent)
        self._cooldown_registrations[matcher] = ("command", str(label))

    def _with_runtime_hooks(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        if self._runtime_context_token is None:
            return kwargs
        updated = dict(kwargs)
        state = dict(updated.get("state") or {})
        state[RUNTIME_CONTEXT_TOKEN_STATE_KEY] = self._runtime_context_token
        updated["state"] = state
        return updated


def _default_semantic_request(
    *,
    command_id: str,
    label: str,
    event: MessageEvent,
    _state: T_State,
) -> SemanticRequest | None:
    target = normalized_text_target(event.get_plaintext())
    if target is None:
        return None
    return SemanticRequest(
        action=ActionDefinition(
            id=command_id,
            label=label,
            cooldown_key=command_id,
        ),
        target=target,
        source=SemanticRequestSource.DIRECT,
    )
