# SPDX-License-Identifier: MIT
from __future__ import annotations

from asyncio import get_running_loop
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import partial
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, TypeAlias, TypeVar, cast

from nonebot.adapters import Event, Message, MessageSegment, MessageTemplate
from nonebot.adapters.onebot.v11 import MessageEvent
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
REPLY_BEFORE_SEND_STATE_KEY = "_ironsbot_reply_before_send"
PROMPT_SESSION_MANAGER_STATE_KEY = "_ironsbot_prompt_session_manager"
TEMP_MATCHER_STATE_TOKEN_KEY = "_ironsbot_temp_matcher_state_token"
_COMMAND_COOLDOWN_TOKEN_KEY = "_ironsbot_command_cooldown_token"  # nosec B105
T_Message: TypeAlias = str | Message | MessageSegment | MessageTemplate
T = TypeVar("T")


class _AsyncPartial(partial):
    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        result: Awaitable[Any] = super().__call__(*args, **kwargs)
        return await result


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


@dataclass(slots=True)
class _TemporaryMatcherState:
    state: T_State
    expiry_handle: TimerHandle


class PromptSessionManager:
    _temporary_matcher_states: ClassVar[dict[str, _TemporaryMatcherState]] = {}

    def __init__(self) -> None:
        self._versions: dict[str, int] = {}

    def acquire(self, session_id: str) -> int:
        version = self._versions.get(session_id, 0) + 1
        self._versions[session_id] = version
        return version

    def invalidate(self, session_id: str) -> None:
        self.acquire(session_id)

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


def get_prompt_session_manager(
    source: Matcher | dict[Any, Any],
) -> PromptSessionManager:
    state = source if isinstance(source, dict) else source.state
    manager = state.get(PROMPT_SESSION_MANAGER_STATE_KEY)
    if not isinstance(manager, PromptSessionManager):
        raise PromptSessionManagerMissingError
    return manager


async def reject_with_rule(
    matcher: Matcher,
    rule: Rule,
    prompt: T_Message | None = None,
    **kwargs: Any,
) -> None:
    if prompt is not None:
        await matcher.send(prompt, **kwargs)

    matcher.remain_handlers.insert(0, current_handler.get())
    if REJECT_CACHE_TARGET in matcher.state:
        matcher.state[REJECT_TARGET] = matcher.state[REJECT_CACHE_TARGET]
    await _create_temp_matcher(matcher, rule)
    raise FinishedException


async def enter_prompt_loop(
    matcher: Matcher,
    handlers: list[Any],
    rule: Rule,
    prompt: T_Message | None = None,
    **kwargs: Any,
) -> None:
    if prompt is not None:
        await matcher.send(prompt, **kwargs)
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
        if self.before_reply_send is None and self.prompt_session_manager is None:
            return kwargs
        updated = dict(kwargs)
        state = dict(updated.get("state") or {})
        if self.before_reply_send is not None:
            state[REPLY_BEFORE_SEND_STATE_KEY] = self.before_reply_send
        if self.prompt_session_manager is not None:
            state[PROMPT_SESSION_MANAGER_STATE_KEY] = self.prompt_session_manager
        updated["state"] = state
        return updated


def _static_command_id(command_id: str) -> CommandIdResolver:
    def resolve(_event: MessageEvent, _state: T_State) -> str:
        return command_id

    return resolve
