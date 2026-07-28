# SPDX-License-Identifier: MIT
from __future__ import annotations

from asyncio import Future, get_running_loop
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from functools import partial
from inspect import Signature, signature
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, TypeAlias, TypeVar, cast

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
from nonebot.typing import T_State

if TYPE_CHECKING:
    from asyncio import TimerHandle
    from datetime import timedelta

ReplyBeforeSend = Callable[[Event | None], Awaitable[None]]
CommandIdResolver = Callable[[MessageEvent, T_State], str | None]
CommandIdSource = str | CommandIdResolver
RUNTIME_CONTEXT_TOKEN_STATE_KEY = "_ironsbot_runtime_context_token"
TEMP_MATCHER_STATE_TOKEN_KEY = "_ironsbot_temp_matcher_state_token"
QUEUED_CONVERSATION_TOKEN_STATE_KEY = "_ironsbot_queued_conversation_token"
QUEUED_CONVERSATION_TICKET_STATE_KEY = "_ironsbot_queued_conversation_ticket"
_COMMAND_COOLDOWN_TOKEN_KEY = "_ironsbot_command_cooldown_token"  # nosec B105
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


class CooldownDecision(Protocol):
    @property
    def allowed(self) -> bool: ...

    @property
    def token(self) -> object | None: ...

    @property
    def feedback(self) -> str | None: ...


class CommandCooldown(Protocol):
    def admit(
        self,
        *,
        user_id: int,
        command_id: str,
        now: float | None = None,
    ) -> CooldownDecision: ...

    def finish(self, token: object) -> None: ...


class PromptSessionManagerMissingError(RuntimeError):
    pass


class PromptLoopConfigurationError(ValueError):
    def __init__(self) -> None:
        super().__init__("queued prompt requires a reply check")


@dataclass(frozen=True, slots=True)
class _MatcherRuntimeContext:
    before_reply_send: ReplyBeforeSend | None
    prompt_session_manager: PromptSessionManager | None


_MATCHER_RUNTIME_CONTEXTS: dict[str, _MatcherRuntimeContext] = {}


@dataclass(slots=True)
class _TemporaryMatcherState:
    state: T_State
    expiry_handle: TimerHandle


@dataclass(slots=True)
class _QueuedConversation:
    token: str
    key: str
    namespace: str
    event_session_id: str
    state: T_State
    reply_check: Callable[[Event], bool]
    handlers: list[Any]
    active: bool = True
    keep_open: bool = False
    _next_ticket: int = 0
    _active_ticket: int | None = None
    _waiters: deque[tuple[int, Future[bool]]] = field(default_factory=deque)

    def matches(self, event: Event) -> bool:
        return self.active and self.reply_check(event)

    def update_reply_check(self, reply_check: Callable[[Event], bool]) -> None:
        self.reply_check = reply_check

    async def acquire(self) -> int | None:
        if not self.active:
            return None
        self._next_ticket += 1
        ticket = self._next_ticket
        future: Future[bool] = get_running_loop().create_future()
        if self._active_ticket is None:
            self._active_ticket = ticket
            future.set_result(True)
        else:
            self._waiters.append((ticket, future))
        try:
            await future
        except BaseException:
            self._waiters = deque(
                item for item in self._waiters if item[0] != ticket
            )
            raise
        return ticket if self.active else None

    def complete(self, ticket: int) -> None:
        if self._active_ticket != ticket:
            return
        self._active_ticket = None
        while self._waiters:
            next_ticket, future = self._waiters.popleft()
            if future.cancelled():
                continue
            self._active_ticket = next_ticket
            future.set_result(True)
            break

    def close(self) -> None:
        self.active = False
        self.keep_open = False
        for _, future in self._waiters:
            if not future.done():
                future.cancel()
        self._waiters.clear()


class PromptSessionManager:
    _temporary_matcher_states: ClassVar[dict[str, _TemporaryMatcherState]] = {}

    def __init__(self) -> None:
        self._versions: dict[str, int] = {}
        self._queued_by_key: dict[str, _QueuedConversation] = {}
        self._queued_by_token: dict[str, _QueuedConversation] = {}
        self._queued_expiry_handles: dict[str, TimerHandle] = {}
        self._cancelled_queued_tokens: set[str] = set()

    def acquire(self, session_id: str) -> int:
        version = self._versions.get(session_id, 0) + 1
        self._versions[session_id] = version
        return version

    def invalidate(self, session_id: str) -> None:
        self.acquire(session_id)

    def invalidate_event_conversations(self, event: Event) -> None:
        event_session_id = event.get_session_id()
        for context in tuple(self._queued_by_token.values()):
            if context.event_session_id == event_session_id:
                self._cancel_queued_conversation(context)

    def start_queued_conversation(
        self,
        *,
        namespace: str,
        event_session_id: str,
        state: T_State,
        reply_check: Callable[[Event], bool],
        handlers: list[Any],
    ) -> _QueuedConversation:
        key = f"{namespace}:{event_session_id}"
        if existing := self._queued_by_key.get(key):
            self._cancel_queued_conversation(existing)
        saved_state = dict(state)
        saved_state.pop(_COMMAND_COOLDOWN_TOKEN_KEY, None)
        context = _QueuedConversation(
            token=token_urlsafe(18),
            key=key,
            namespace=namespace,
            event_session_id=event_session_id,
            state=saved_state,
            reply_check=reply_check,
            handlers=handlers,
        )
        self._queued_by_key[key] = context
        self._queued_by_token[context.token] = context
        return context

    def queued_conversation(
        self,
        state: T_State,
    ) -> _QueuedConversation | None:
        token = state.get(QUEUED_CONVERSATION_TOKEN_STATE_KEY)
        if not isinstance(token, str):
            return None
        return self._queued_by_token.get(token)

    def finish_queued_conversation(self, state: T_State) -> None:
        context = self.queued_conversation(state)
        ticket = state.get(QUEUED_CONVERSATION_TICKET_STATE_KEY)
        token = state.pop(QUEUED_CONVERSATION_TOKEN_STATE_KEY, None)
        state.pop(QUEUED_CONVERSATION_TICKET_STATE_KEY, None)
        if context is None or not isinstance(ticket, int):
            if isinstance(token, str) and isinstance(ticket, int):
                self._cancelled_queued_tokens.discard(token)
            return
        if not context.active or not context.keep_open:
            self._close_queued_conversation(context)
            return
        context.keep_open = False
        context.state = dict(state)
        context.complete(ticket)

    def cancel_queued_conversation(self, state: T_State) -> None:
        if context := self.queued_conversation(state):
            self._cancel_queued_conversation(context)

    def queued_conversation_is_cancelled(self, state: T_State) -> bool:
        token = state.get(QUEUED_CONVERSATION_TOKEN_STATE_KEY)
        return isinstance(token, str) and token in self._cancelled_queued_tokens

    def refresh_queued_conversation_expiry(
        self,
        context: _QueuedConversation,
        *,
        expires_after: timedelta,
    ) -> None:
        if previous := self._queued_expiry_handles.pop(context.token, None):
            previous.cancel()
        self._queued_expiry_handles[context.token] = get_running_loop().call_later(
            max(expires_after.total_seconds(), 0),
            self._expire_queued_conversation,
            context.token,
        )

    def _close_queued_conversation(self, context: _QueuedConversation) -> None:
        if expiry_handle := self._queued_expiry_handles.pop(context.token, None):
            expiry_handle.cancel()
        context.close()
        self._queued_by_key.pop(context.key, None)
        self._queued_by_token.pop(context.token, None)

    def _cancel_queued_conversation(self, context: _QueuedConversation) -> None:
        if context._active_ticket is not None:
            self._cancelled_queued_tokens.add(context.token)
        self._close_queued_conversation(context)

    def _expire_queued_conversation(self, token: str) -> None:
        self._queued_expiry_handles.pop(token, None)
        if context := self._queued_by_token.get(token):
            self._cancel_queued_conversation(context)

    def make_rule(
        self,
        session_id: str,
        version: int,
        content_check: Callable[[Event], bool],
    ) -> Rule:
        def check(event: Event) -> bool:
            return (
                self._versions.get(session_id) == version
                and content_check(event)
            )

        return Rule(check)

    @classmethod
    def store_temporary_matcher_state(
        cls,
        state: T_State,
        *,
        expires_after: timedelta,
    ) -> str:
        token = token_urlsafe(18)
        expiry_handle = get_running_loop().call_later(
            max(expires_after.total_seconds(), 0),
            cls._discard_temporary_matcher_state,
            token,
        )
        cls._temporary_matcher_states[token] = _TemporaryMatcherState(
            state=state,
            expiry_handle=expiry_handle,
        )
        return token

    @classmethod
    def take_temporary_matcher_state(cls, token: str) -> T_State | None:
        stored = cls._temporary_matcher_states.pop(token, None)
        if stored is None:
            return None
        stored.expiry_handle.cancel()
        return stored.state

    @classmethod
    def _discard_temporary_matcher_state(cls, token: str) -> None:
        cls._temporary_matcher_states.pop(token, None)


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
    context = _runtime_context(source)
    return None if context is None else context.before_reply_send


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
                context.keep_open = True
                raise FinishedException
            get_prompt_session_manager(matcher).cancel_queued_conversation(
                matcher.state
            )
            matcher.state.pop(QUEUED_CONVERSATION_TOKEN_STATE_KEY, None)
            matcher.state.pop(QUEUED_CONVERSATION_TICKET_STATE_KEY, None)
        event = current_event.get()
        prompt_sessions = get_prompt_session_manager(matcher)
        queued = prompt_sessions.start_queued_conversation(
            namespace=queue_namespace,
            event_session_id=event.get_session_id(),
            state=matcher.state,
            reply_check=queue_reply_check,
            handlers=handlers,
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


async def _capture_queued_conversation_input(
    matcher: Matcher,
    event: Event,
    state: T_State,
) -> None:
    context = get_queued_conversation(state)
    if context is None or not context.active:
        raise FinishedException

    if not isinstance(event, MessageEvent):
        raise FinishedException

    if event.get_plaintext().strip() == "0":
        get_prompt_session_manager(state).cancel_queued_conversation(state)
        if getattr(event, "group_id", None) is not None:
            await matcher.finish(
                OneBotMessageSegment.at(event.user_id)
                + OneBotMessageSegment.text(" 已退出当前选择。")
            )
        await matcher.finish("已退出当前选择。")

    await _create_queued_temp_matcher(matcher, context)
    ticket = await context.acquire()
    if ticket is None:
        raise FinishedException
    state.clear()
    state.update(context.state)
    state[QUEUED_CONVERSATION_TOKEN_STATE_KEY] = context.token
    state[QUEUED_CONVERSATION_TICKET_STATE_KEY] = ticket


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
    cooldown: CommandCooldown
    priorities: object
    before_reply_send: ReplyBeforeSend | None = None
    prompt_session_manager: PromptSessionManager | None = None
    _message_matchers: list[type[Matcher]] = field(default_factory=list)
    _notice_matchers: list[type[Matcher]] = field(default_factory=list)
    _cooldown_registrations: dict[type[Matcher], tuple[str, str]] = field(
        default_factory=dict
    )
    _runtime_context_token: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.before_reply_send is None and self.prompt_session_manager is None:
            return
        token = token_urlsafe(18)
        _MATCHER_RUNTIME_CONTEXTS[token] = _MatcherRuntimeContext(
            before_reply_send=self.before_reply_send,
            prompt_session_manager=self.prompt_session_manager,
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

    def _register_message(
        self,
        matcher: type[Matcher],
        policy: CommandPolicy,
    ) -> type[Matcher]:
        if policy.command_id is not None:
            self._install_cooldown(matcher, policy.command_id)
        else:
            self._cooldown_registrations[matcher] = (
                "exempt",
                policy.exemption_reason or "",
            )
        self._message_matchers.append(matcher)
        return matcher

    def _install_cooldown(
        self,
        matcher: type[Matcher],
        command_id: CommandIdSource,
    ) -> None:
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

            decision = self.cooldown.admit(
                user_id=event.user_id,
                command_id=normalized_id,
            )
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


def _static_command_id(command_id: str) -> CommandIdResolver:
    def resolve(_event: MessageEvent, _state: T_State) -> str:
        return command_id

    return resolve
