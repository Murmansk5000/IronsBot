# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any, TypeAlias

from nonebot.adapters import Event, Message, MessageSegment, MessageTemplate
from nonebot.adapters.onebot.v11 import (
    MessageEvent,  # noqa: TC002 - NoneBot resolves it at runtime
)
from nonebot.consts import REJECT_CACHE_TARGET, REJECT_TARGET
from nonebot.dependencies import Dependent
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.matcher import Matcher, current_bot, current_event, current_handler
from nonebot.message import run_postprocessor
from nonebot.plugin import on_command, on_fullmatch, on_message, on_notice
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves handler annotations

if TYPE_CHECKING:
    from ironsbot.core.request_coordination import RequestCoordinator
    from ironsbot.runtime.commands import CommandCatalog
    from ironsbot.runtime.matcher_contracts import (
        CommandCooldown,
        CommandIdSource,
        QueuedSemanticRequestResolver,
        SemanticRequestResolver,
    )
    from ironsbot.runtime.prompt_sessions import _QueuedConversation
from ironsbot.runtime.bindings import bind, bind_async  # noqa: F401
from ironsbot.runtime.matcher_contracts import (
    CommandPolicyError,
    default_semantic_request,
    static_command_id,
)
from ironsbot.runtime.onebot_context import event_request_scope
from ironsbot.runtime.prompt_errors import (
    PromptLoopConfigurationError,
    PromptSessionManagerMissingError,
)
from ironsbot.runtime.prompt_sessions import (
    COMMAND_COOLDOWN_TOKEN_STATE_KEY as _COMMAND_COOLDOWN_TOKEN_KEY,
)
from ironsbot.runtime.prompt_sessions import (
    QUEUED_CONVERSATION_KEEP_OPEN_STATE_KEY,
    QUEUED_CONVERSATION_TICKET_STATE_KEY,
    QUEUED_CONVERSATION_TOKEN_STATE_KEY,
    TEMP_MATCHER_STATE_TOKEN_KEY,
    GroupMenuAnchor,
    PromptSessionManager,
)
from ironsbot.runtime.prompt_sessions import (
    REQUEST_RESPONSE_TOKEN_STATE_KEY as _REQUEST_RESPONSE_TOKEN_KEY,
)
from ironsbot.runtime.queued_conversation_input import (
    capture_queued_conversation_input,
)

RUNTIME_CONTEXT_TOKEN_STATE_KEY = "_ironsbot_runtime_context_token"
SEMANTIC_REQUEST_STATE_KEY = "_ironsbot_semantic_request"
QUEUED_CONVERSATION_EXIT_PRIORITY = -999
QUEUED_CONVERSATION_INPUT_PRIORITY = -998
T_Message: TypeAlias = str | Message | MessageSegment | MessageTemplate


@dataclass(frozen=True, slots=True)
class _MatcherRuntimeContext:
    prompt_session_manager: PromptSessionManager | None
    request_coordinator: RequestCoordinator | None


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


def get_queued_conversation(
    source: Matcher | dict[Any, Any],
) -> _QueuedConversation | None:
    try:
        return get_prompt_session_manager(source).queued_conversation(
            source if isinstance(source, dict) else source.state
        )
    except PromptSessionManagerMissingError:
        return None


def _matches_active_queued_conversation(
    event: Event,
    state: T_State,
) -> bool:
    """Attach the menu context that exclusively owns this message."""

    try:
        prompt_sessions = get_prompt_session_manager(state)
    except PromptSessionManagerMissingError:
        return False
    context = prompt_sessions.matching_queued_conversation(event)
    if context is None:
        return False
    state[QUEUED_CONVERSATION_TOKEN_STATE_KEY] = context.token
    return True


def _matches_active_queued_conversation_exit(
    event: Event,
    state: T_State,
) -> bool:
    """Attach an active menu only for its owner's explicit exit input."""

    if event.get_plaintext().strip() != "0":
        return False
    return _matches_active_queued_conversation(event, state)


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
    *,
    group_reply_check: Callable[[Event], bool] | None = None,
) -> None:
    context = get_queued_conversation(matcher)
    if context is not None:
        context.update_reply_check(reply_check, group_reply_check)


def update_queued_menu_anchor(
    matcher: Matcher,
    event: Event,
    send_result: object,
    *,
    page_id: str | None = None,
) -> None:
    """Replace the shared-reply anchor after emitting a new group menu."""

    context = get_queued_conversation(matcher)
    if context is not None:
        context.update_menu_anchor(_group_menu_anchor(event, send_result))
        if page_id is not None:
            get_prompt_session_manager(matcher).record_menu_page(
                context,
                page_id=page_id,
            )


def _group_menu_anchor(
    event: Event,
    send_result: object,
) -> GroupMenuAnchor | None:
    group_id = getattr(event, "group_id", None)
    bot_user_id = getattr(event, "self_id", None)
    message_id = _send_result_message_id(send_result)
    if (
        not isinstance(group_id, int)
        or not isinstance(bot_user_id, int)
        or bot_user_id <= 0
        or message_id is None
    ):
        return None
    return GroupMenuAnchor(
        group_id=group_id,
        bot_user_id=bot_user_id,
        message_id=message_id,
    )


def _send_result_message_id(send_result: object) -> int | None:
    raw_message_id = (
        send_result.get("message_id")
        if isinstance(send_result, Mapping)
        else getattr(send_result, "message_id", None)
    )
    if isinstance(raw_message_id, bool) or not isinstance(raw_message_id, (int, str)):
        return None
    try:
        message_id = int(raw_message_id)
    except (TypeError, ValueError):
        return None
    return message_id if message_id > 0 else None


async def reject_with_rule(
    matcher: Matcher,
    rule: Rule,
    prompt: T_Message | None = None,
    **kwargs: Any,
) -> None:
    replace_menu_anchor = bool(kwargs.pop("replace_menu_anchor", False))
    page_id = kwargs.pop("page_id", None)
    if queued_conversation_is_cancelled(matcher):
        raise FinishedException
    if prompt is not None:
        send_result = await matcher.send(prompt, **kwargs)
        if replace_menu_anchor:
            update_queued_menu_anchor(
                matcher,
                current_event.get(),
                send_result,
                page_id=page_id,
            )

    if get_queued_conversation(matcher) is not None:
        matcher.state[QUEUED_CONVERSATION_KEEP_OPEN_STATE_KEY] = True
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
    queue_group_reply_check: Callable[[Event], bool] | None = None,
    queue_allow_group_reply_exit: bool = False,
    queue_parallel: bool = False,
    queue_page_id: str = "root",
    queue_semantic_request_resolver: QueuedSemanticRequestResolver | None = None,
    queue_event_session_id: str | None = None,
    queue_conversation_session_id: str | None = None,
    **kwargs: Any,
) -> None:
    if queued_conversation_is_cancelled(matcher):
        raise FinishedException
    event = current_event.get()
    if queue_namespace is not None:
        if queue_reply_check is None:
            raise PromptLoopConfigurationError
        if context := get_queued_conversation(matcher):
            if context.namespace == queue_namespace:
                menu_anchor = context.menu_anchor
                if prompt is not None:
                    send_result = await matcher.send(prompt, **kwargs)
                    menu_anchor = _group_menu_anchor(event, send_result)
                get_prompt_session_manager(matcher).activate_queued_conversation(
                    context,
                    state=matcher.state,
                    reply_check=queue_reply_check,
                    group_reply_check=queue_group_reply_check,
                    menu_anchor=menu_anchor,
                    allow_group_reply_exit=queue_allow_group_reply_exit,
                    semantic_request_resolver=queue_semantic_request_resolver,
                    handlers=handlers,
                    parallel=queue_parallel,
                    page_id=queue_page_id,
                    menu_sent=prompt is not None,
                )
                matcher.state[QUEUED_CONVERSATION_KEEP_OPEN_STATE_KEY] = True
                raise FinishedException
            get_prompt_session_manager(matcher).cancel_queued_conversation(
                matcher.state
            )
            matcher.state.pop(QUEUED_CONVERSATION_TOKEN_STATE_KEY, None)
            matcher.state.pop(QUEUED_CONVERSATION_TICKET_STATE_KEY, None)
        prompt_sessions = get_prompt_session_manager(matcher)
        runtime_context = _runtime_context(matcher)
        raw_owner_user_id = getattr(event, "user_id", None)
        owner_user_id = (
            raw_owner_user_id if isinstance(raw_owner_user_id, int) else None
        )
        queued = prompt_sessions.start_queued_conversation(
            namespace=queue_namespace,
            event_session_id=queue_event_session_id or event.get_session_id(),
            owner_user_id=owner_user_id,
            state=matcher.state,
            reply_check=queue_reply_check,
            group_reply_check=queue_group_reply_check,
            handlers=handlers,
            semantic_request_resolver=queue_semantic_request_resolver,
            request_coordinator=(
                None
                if runtime_context is None
                else runtime_context.request_coordinator
            ),
            conversation_session_id=queue_conversation_session_id,
            menu_anchor=None,
            allow_group_reply_exit=queue_allow_group_reply_exit,
            parallel=queue_parallel,
            pending_reply_check=queue_reply_check,
            pending=True,
        )
        menu_anchor = None
        try:
            if prompt is not None:
                send_result = await matcher.send(prompt, **kwargs)
                menu_anchor = _group_menu_anchor(event, send_result)
        except BaseException:
            prompt_sessions.cancel_queued_context(queued)
            raise
        prompt_sessions.activate_queued_conversation(
            queued,
            state=matcher.state,
            reply_check=queue_reply_check,
            group_reply_check=queue_group_reply_check,
            menu_anchor=menu_anchor,
            allow_group_reply_exit=queue_allow_group_reply_exit,
            semantic_request_resolver=queue_semantic_request_resolver,
            handlers=handlers,
            parallel=queue_parallel,
            page_id=queue_page_id,
            menu_sent=prompt is not None,
        )
        raise FinishedException
    if prompt is not None:
        await matcher.send(prompt, **kwargs)
    await _create_temp_matcher(matcher, rule, handlers=handlers)
    raise FinishedException


async def begin_queued_conversation(  # noqa: PLR0913
    matcher: Matcher,
    handlers: list[Any],
    *,
    namespace: str,
    pending_reply_check: Callable[[Event], bool],
    queue_reply_check: Callable[[Event], bool],
    queue_group_reply_check: Callable[[Event], bool] | None = None,
    queue_allow_group_reply_exit: bool = False,
    queue_parallel: bool = False,
    queue_page_id: str = "root",
    queue_semantic_request_resolver: QueuedSemanticRequestResolver | None = None,
    queue_event_session_id: str | None = None,
    queue_conversation_session_id: str | None = None,
) -> None:
    """Open a queued menu before an asynchronous first-level command finishes."""

    event = current_event.get()
    if context := get_queued_conversation(matcher):
        if context.namespace == namespace:
            return
        get_prompt_session_manager(matcher).cancel_queued_conversation(matcher.state)
        matcher.state.pop(QUEUED_CONVERSATION_TOKEN_STATE_KEY, None)
        matcher.state.pop(QUEUED_CONVERSATION_TICKET_STATE_KEY, None)

    prompt_sessions = get_prompt_session_manager(matcher)
    runtime_context = _runtime_context(matcher)
    raw_owner_user_id = getattr(event, "user_id", None)
    owner_user_id = raw_owner_user_id if isinstance(raw_owner_user_id, int) else None
    queued = prompt_sessions.start_queued_conversation(
        namespace=namespace,
        event_session_id=queue_event_session_id or event.get_session_id(),
        owner_user_id=owner_user_id,
        state=matcher.state,
        reply_check=queue_reply_check,
        group_reply_check=queue_group_reply_check,
        handlers=handlers,
        page_id=queue_page_id,
        semantic_request_resolver=queue_semantic_request_resolver,
        request_coordinator=(
            None if runtime_context is None else runtime_context.request_coordinator
        ),
        conversation_session_id=queue_conversation_session_id,
        allow_group_reply_exit=queue_allow_group_reply_exit,
        parallel=queue_parallel,
        pending_reply_check=pending_reply_check,
        pending=True,
    )
    matcher.state[QUEUED_CONVERSATION_TOKEN_STATE_KEY] = queued.token


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


async def _capture_queued_conversation_input(
    matcher: Matcher,
    event: Event,
    _state: T_State,
) -> None:
    await capture_queued_conversation_input(
        matcher,
        event,
        _state,
        get_prompt_sessions=get_prompt_session_manager,
        dispatch_handlers=_dispatch_queued_conversation_handlers,
    )


def _dispatch_queued_conversation_handlers(
    matcher: Matcher,
    context: _QueuedConversation,
) -> None:
    """Append this input's current menu handler after stable routing."""

    for handler in context.handlers:
        matcher.remain_handlers.append(
            handler
            if isinstance(handler, Dependent)
            else Dependent[Any].parse(
                call=handler,
                allow_types=matcher.__class__.HANDLER_PARAM_TYPES,
            )
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
    prompt_session_manager: PromptSessionManager | None = None
    request_coordinator: RequestCoordinator | None = None
    _message_matchers: list[type[Matcher]] = field(default_factory=list)
    _notice_matchers: list[type[Matcher]] = field(default_factory=list)
    _cooldown_registrations: dict[type[Matcher], tuple[str, str]] = field(
        default_factory=dict
    )
    _command_help_ids: set[str] = field(default_factory=set)
    _unclassified_command_labels: set[str] = field(default_factory=set)
    _runtime_context_token: str | None = field(default=None, init=False, repr=False)
    _queued_router_installed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            self.prompt_session_manager is None
            and self.request_coordinator is None
        ):
            return
        token = token_urlsafe(18)
        _MATCHER_RUNTIME_CONTEXTS[token] = _MatcherRuntimeContext(
            prompt_session_manager=self.prompt_session_manager,
            request_coordinator=self.request_coordinator,
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
            token = state.pop(_REQUEST_RESPONSE_TOKEN_KEY, None)
            if token is not None and self.request_coordinator is not None:
                self.request_coordinator.finish(token)
            token = state.pop(_COMMAND_COOLDOWN_TOKEN_KEY, None)
            if token is not None:
                self.cooldown.finish(token)

    def install_queued_conversation_router(self) -> None:
        """Install one durable ingress matcher for every active menu session."""

        if self.prompt_session_manager is None or self._queued_router_installed:
            return

        self._queued_router_installed = True

        exit_matcher = self.on_message(
            policy=CommandPolicy.exempt("active queued conversation exit"),
            rule=Rule(_matches_active_queued_conversation_exit),
            priority=QUEUED_CONVERSATION_EXIT_PRIORITY,
            block=True,
        )
        exit_matcher.append_handler(_capture_queued_conversation_input)

        matcher = self.on_message(
            policy=CommandPolicy.exempt("active queued conversation input"),
            rule=Rule(_matches_active_queued_conversation),
            # Blacklist is -1000. These permanent routers run immediately
            # afterwards and never share a priority with configurable matchers.
            priority=QUEUED_CONVERSATION_INPUT_PRIORITY,
            block=True,
        )
        matcher.append_handler(_capture_queued_conversation_input)

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
                else default_semantic_request(
                    command_id=normalized_id,
                    label=str(label),
                    event=event,
                    state=state,
                )
            )
            if request is not None:
                state[SEMANTIC_REQUEST_STATE_KEY] = request
                if self.request_coordinator is not None:
                    request_decision = self.request_coordinator.admit(
                        user_id=event.user_id,
                        request=request,
                        scope=event_request_scope(event),
                    )
                    if request_decision.token is not None:
                        state[_REQUEST_RESPONSE_TOKEN_KEY] = request_decision.token
                    if not request_decision.allowed:
                        await matcher.finish(request_decision.feedback)

            decision = self.cooldown.admit(
                user_id=event.user_id,
                command_id=normalized_id,
            )
            if not decision.allowed:
                request_token = state.pop(_REQUEST_RESPONSE_TOKEN_KEY, None)
                if request_token is not None and self.request_coordinator is not None:
                    self.request_coordinator.release(request_token)
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
