# SPDX-License-Identifier: MIT
"""State kept outside NoneBot matcher defaults for temporary prompt sessions."""

from __future__ import annotations

from asyncio import Future, get_running_loop
from collections import deque
from dataclasses import dataclass, field
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any, ClassVar

# NoneBot resolves Rule callback annotations when creating temporary matchers.
from nonebot.adapters import Event  # noqa: TC002
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.rule import Rule

from ironsbot.runtime.onebot_reply import event_reply_message_id

if TYPE_CHECKING:
    from asyncio import TimerHandle
    from collections.abc import Callable
    from datetime import timedelta

    from nonebot.typing import T_State

    from ironsbot.core.request_coordination import RequestCoordinator
    from ironsbot.runtime.matcher_contracts import QueuedSemanticRequestResolver

TEMP_MATCHER_STATE_TOKEN_KEY = "_ironsbot_temp_matcher_state_token"
QUEUED_CONVERSATION_TOKEN_STATE_KEY = "_ironsbot_queued_conversation_token"
QUEUED_CONVERSATION_TICKET_STATE_KEY = "_ironsbot_queued_conversation_ticket"
QUEUED_CONVERSATION_KEEP_OPEN_STATE_KEY = "_ironsbot_queued_conversation_keep_open"
QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY = (
    "_ironsbot_queued_conversation_shared_reply"
)
COMMAND_COOLDOWN_TOKEN_STATE_KEY = "_ironsbot_command_cooldown_token"  # nosec B105
REQUEST_RESPONSE_TOKEN_STATE_KEY = "_ironsbot_request_response_token"  # nosec B105
MAX_CLAIMED_MENU_INPUTS = 4096


@dataclass(frozen=True, slots=True)
class GroupMenuAnchor:
    """Identity of the latest group menu message emitted by the bot."""

    group_id: int
    bot_user_id: int
    message_id: int


def is_current_group_menu_reply(
    event: Event,
    anchor: GroupMenuAnchor | None,
) -> bool:
    """Return whether an event precisely replies to the tracked bot menu."""

    if anchor is None or not isinstance(event, GroupMessageEvent):
        return False
    if event.group_id != anchor.group_id or event.self_id != anchor.bot_user_id:
        return False
    if event.user_id == event.self_id:
        return False
    # The reply sender metadata is optional in OneBot events.  The tracked
    # message ID was obtained from the bot's own send result, so it is the
    # authoritative proof that this is a reply to the current bot menu.
    return event_reply_message_id(event) == anchor.message_id


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
    owner_user_id: int | None
    state: T_State
    reply_check: Callable[[Event], bool]
    group_reply_check: Callable[[Event], bool] | None
    handlers: list[Any]
    conversation_session_id: str | None = None
    menu_anchor: GroupMenuAnchor | None = None
    allow_group_reply_exit: bool = False
    semantic_request_resolver: QueuedSemanticRequestResolver | None = None
    request_coordinator: RequestCoordinator | None = None
    active: bool = True
    parallel: bool = False
    pending_reply_check: Callable[[Event], bool] | None = None
    pending: bool = False
    _activation: Future[bool] | None = field(default=None, init=False, repr=False)
    _next_ticket: int = 0
    _active_ticket: int | None = None
    _active_request_token: object | None = None
    _parallel_request_tokens: dict[int, object | None] = field(default_factory=dict)
    _parallel_ready_ticket: int | None = None
    _parallel_dispatched: set[int] = field(default_factory=set)
    _parallel_waiters: deque[tuple[int, Future[bool]]] = field(default_factory=deque)
    _waiters: deque[tuple[int, Future[bool], object | None]] = field(
        default_factory=deque
    )

    def __post_init__(self) -> None:
        if self.conversation_session_id is None:
            self.conversation_session_id = self.event_session_id

    def matches(self, event: Event) -> bool:
        if not self.active:
            return False
        if self.pending:
            return self.pending_reply_check is not None and self.pending_reply_check(
                event
            )
        if self.reply_check(event):
            return True
        if (
            self.owner_user_id is not None
            and getattr(event, "user_id", None) != self.owner_user_id
            and event.get_plaintext().strip() == "0"
            and not self.allow_group_reply_exit
        ):
            return False
        return (
            self.group_reply_check is not None
            and is_current_group_menu_reply(event, self.menu_anchor)
            and self.group_reply_check(event)
        )

    def is_shared_group_reply(self, event: Event) -> bool:
        """Return whether this event is a different member using this menu."""

        return (
            self.owner_user_id is not None
            and getattr(event, "user_id", None) != self.owner_user_id
            and self.group_reply_check is not None
            and is_current_group_menu_reply(event, self.menu_anchor)
            and self.group_reply_check(event)
        )

    def update_reply_check(
        self,
        reply_check: Callable[[Event], bool],
        group_reply_check: Callable[[Event], bool] | None = None,
    ) -> None:
        self.reply_check = reply_check
        self.group_reply_check = group_reply_check

    def update_menu_anchor(self, anchor: GroupMenuAnchor | None) -> None:
        self.menu_anchor = anchor

    def update_allow_group_reply_exit(self, *, allowed: bool) -> None:
        self.allow_group_reply_exit = allowed

    def update_semantic_request_resolver(
        self,
        resolver: QueuedSemanticRequestResolver | None,
    ) -> None:
        self.semantic_request_resolver = resolver

    def activate(  # noqa: PLR0913
        self,
        *,
        state: T_State,
        reply_check: Callable[[Event], bool],
        group_reply_check: Callable[[Event], bool] | None,
        menu_anchor: GroupMenuAnchor | None,
        allow_group_reply_exit: bool,
        semantic_request_resolver: QueuedSemanticRequestResolver | None,
    ) -> None:
        """Make a pre-menu conversation ready after its prompt is sent."""

        self.state = self._saved_state(state)
        self.update_reply_check(reply_check, group_reply_check)
        self.update_menu_anchor(menu_anchor)
        self.update_allow_group_reply_exit(allowed=allow_group_reply_exit)
        self.update_semantic_request_resolver(semantic_request_resolver)
        self.pending = False
        if self._activation is not None and not self._activation.done():
            self._activation.set_result(self.active)

    async def wait_until_active(self) -> bool:
        if not self.pending:
            return self.active
        if self._activation is None:
            self._activation = get_running_loop().create_future()
        return await self._activation

    def reserve(
        self,
        request_token: object | None = None,
    ) -> tuple[int, Future[bool]] | None:
        if not self.active:
            self._release_request_token(request_token)
            return None
        self._next_ticket += 1
        ticket = self._next_ticket
        future: Future[bool] = get_running_loop().create_future()
        if self.parallel:
            self._parallel_request_tokens[ticket] = request_token
            if self._parallel_ready_ticket is None:
                self._parallel_ready_ticket = ticket
                future.set_result(True)
            else:
                self._parallel_waiters.append((ticket, future))
        elif self._active_ticket is None:
            self._active_ticket = ticket
            self._active_request_token = request_token
            future.set_result(True)
        else:
            self._waiters.append((ticket, future, request_token))
        return ticket, future

    async def acquire(self, request_token: object | None = None) -> int | None:
        reservation = self.reserve(request_token)
        if reservation is None:
            return None
        ticket, future = reservation
        try:
            await future
        except BaseException:
            self.abort(ticket)
            raise
        if self.active:
            return ticket
        self.abort(ticket)
        return None

    def complete(self, ticket: int) -> None:
        if self.parallel:
            self._parallel_dispatched.discard(ticket)
            self._parallel_request_tokens.pop(ticket, None)
            return
        if self._active_ticket != ticket:
            return
        self._active_ticket = None
        self._active_request_token = None
        while self._waiters:
            next_ticket, future, request_token = self._waiters.popleft()
            if future.cancelled():
                self._release_request_token(request_token)
                continue
            self._active_ticket = next_ticket
            self._active_request_token = request_token
            future.set_result(True)
            break

    def abort(self, ticket: int) -> None:
        if self.parallel:
            token = self._parallel_request_tokens.pop(ticket, None)
            self._parallel_dispatched.discard(ticket)
            if self._parallel_ready_ticket == ticket:
                self._parallel_ready_ticket = None
                self._advance_parallel_dispatch()
            else:
                parallel_retained: deque[tuple[int, Future[bool]]] = deque()
                for queued_ticket, future in self._parallel_waiters:
                    if queued_ticket == ticket:
                        if not future.done():
                            future.cancel()
                        continue
                    parallel_retained.append((queued_ticket, future))
                self._parallel_waiters = parallel_retained
            self._release_request_token(token)
            return
        if self._active_ticket == ticket:
            token = self._active_request_token
            self.complete(ticket)
            self._release_request_token(token)
            return
        retained: deque[tuple[int, Future[bool], object | None]] = deque()
        for item in self._waiters:
            if item[0] == ticket:
                self._release_request_token(item[2])
                if not item[1].done():
                    item[1].cancel()
                continue
            retained.append(item)
        self._waiters = retained

    @property
    def active_ticket_count(self) -> int:
        if self.parallel:
            return len(self._parallel_dispatched)
        return int(self._active_ticket is not None)

    def mark_dispatched(self, ticket: int) -> None:
        if not self.parallel or self._parallel_ready_ticket != ticket:
            return
        self._parallel_dispatched.add(ticket)
        self._parallel_ready_ticket = None
        self._advance_parallel_dispatch()

    def close(self) -> None:
        self.active = False
        if self._activation is not None and not self._activation.done():
            self._activation.set_result(False)
        if self.parallel:
            pending_tickets = {ticket for ticket, _future in self._parallel_waiters}
            if self._parallel_ready_ticket is not None:
                pending_tickets.add(self._parallel_ready_ticket)
            for ticket in pending_tickets:
                self._release_request_token(
                    self._parallel_request_tokens.pop(ticket, None)
                )
            for _, future in self._parallel_waiters:
                if not future.done():
                    future.cancel()
            self._parallel_waiters.clear()
            self._parallel_ready_ticket = None
        for _, future, request_token in self._waiters:
            self._release_request_token(request_token)
            if not future.done():
                future.cancel()
        self._waiters.clear()

    def _release_request_token(self, token: object | None) -> None:
        if token is not None and self.request_coordinator is not None:
            self.request_coordinator.release(token)

    @staticmethod
    def _saved_state(state: T_State) -> T_State:
        saved_state = dict(state)
        saved_state.pop(COMMAND_COOLDOWN_TOKEN_STATE_KEY, None)
        saved_state.pop(REQUEST_RESPONSE_TOKEN_STATE_KEY, None)
        saved_state.pop(QUEUED_CONVERSATION_TOKEN_STATE_KEY, None)
        saved_state.pop(QUEUED_CONVERSATION_TICKET_STATE_KEY, None)
        return saved_state

    def _advance_parallel_dispatch(self) -> None:
        while self.active and self._parallel_waiters:
            ticket, future = self._parallel_waiters.popleft()
            if future.cancelled():
                self._release_request_token(
                    self._parallel_request_tokens.pop(ticket, None)
                )
                continue
            self._parallel_ready_ticket = ticket
            future.set_result(True)
            return


class PromptSessionManager:
    _temporary_matcher_states: ClassVar[dict[str, _TemporaryMatcherState]] = {}

    def __init__(self) -> None:
        self._versions: dict[str, int] = {}
        self._queued_by_key: dict[str, _QueuedConversation] = {}
        self._queued_by_token: dict[str, _QueuedConversation] = {}
        self._queued_expiry_handles: dict[str, TimerHandle] = {}
        self._cancelled_queued_tokens: set[str] = set()
        self._cancelled_active_tickets: dict[str, int] = {}
        self._claimed_inputs: dict[tuple[int, str, int], None] = {}

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

    def start_queued_conversation(  # noqa: PLR0913
        self,
        *,
        namespace: str,
        event_session_id: str,
        state: T_State,
        owner_user_id: int | None = None,
        reply_check: Callable[[Event], bool],
        group_reply_check: Callable[[Event], bool] | None = None,
        handlers: list[Any],
        semantic_request_resolver: QueuedSemanticRequestResolver | None = None,
        request_coordinator: RequestCoordinator | None = None,
        conversation_session_id: str | None = None,
        menu_anchor: GroupMenuAnchor | None = None,
        allow_group_reply_exit: bool = False,
        parallel: bool = False,
        pending_reply_check: Callable[[Event], bool] | None = None,
        pending: bool = False,
    ) -> _QueuedConversation:
        key = f"{namespace}:{event_session_id}"
        if existing := self._queued_by_key.get(key):
            self._cancel_queued_conversation(existing)
        context = _QueuedConversation(
            token=token_urlsafe(18),
            key=key,
            namespace=namespace,
            event_session_id=event_session_id,
            owner_user_id=owner_user_id,
            state=_QueuedConversation._saved_state(state),
            reply_check=reply_check,
            group_reply_check=group_reply_check,
            handlers=handlers,
            conversation_session_id=conversation_session_id,
            menu_anchor=menu_anchor,
            allow_group_reply_exit=allow_group_reply_exit,
            parallel=parallel,
            pending_reply_check=pending_reply_check,
            pending=pending,
            semantic_request_resolver=semantic_request_resolver,
            request_coordinator=request_coordinator,
        )
        self._queued_by_key[key] = context
        self._queued_by_token[context.token] = context
        return context

    def queued_conversation(self, state: T_State) -> _QueuedConversation | None:
        token = state.get(QUEUED_CONVERSATION_TOKEN_STATE_KEY)
        if not isinstance(token, str):
            return None
        return self._queued_by_token.get(token)

    def finish_queued_conversation(self, state: T_State) -> None:
        context = self.queued_conversation(state)
        ticket = state.get(QUEUED_CONVERSATION_TICKET_STATE_KEY)
        token = state.pop(QUEUED_CONVERSATION_TOKEN_STATE_KEY, None)
        state.pop(QUEUED_CONVERSATION_TICKET_STATE_KEY, None)
        keep_open = bool(state.pop(QUEUED_CONVERSATION_KEEP_OPEN_STATE_KEY, False))
        if context is None or not isinstance(ticket, int):
            if context is not None and context.pending:
                self._cancel_queued_conversation(context)
            if isinstance(token, str) and isinstance(ticket, int):
                self._finish_cancelled_ticket(token)
            return
        context.complete(ticket)
        if not context.active:
            self._close_queued_conversation(context)
            return
        if not keep_open:
            if context.parallel:
                return
            self._close_queued_conversation(context)
            return
        context.state = _QueuedConversation._saved_state(state)

    def cancel_queued_conversation(self, state: T_State) -> None:
        if context := self.queued_conversation(state):
            self._cancel_queued_conversation(context)

    def cancel_queued_context(self, context: _QueuedConversation) -> None:
        """Cancel a context retained before it is attached to matcher state."""

        self._cancel_queued_conversation(context)

    def detach_queued_conversation(self, state: T_State) -> _QueuedConversation | None:
        """Release this matcher state without closing the retained conversation."""

        context = self.queued_conversation(state)
        ticket = state.pop(QUEUED_CONVERSATION_TICKET_STATE_KEY, None)
        state.pop(QUEUED_CONVERSATION_TOKEN_STATE_KEY, None)
        state.pop(QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY, None)
        if context is not None and isinstance(ticket, int):
            context.complete(ticket)
        return context

    def claim_input(self, event: Event) -> bool:
        raw_message_id = getattr(event, "message_id", None)
        if raw_message_id is None:
            message_id = id(event)
        else:
            try:
                message_id = int(raw_message_id)
            except (TypeError, ValueError):
                message_id = id(event)
        key = (
            int(getattr(event, "self_id", 0) or 0),
            event.get_session_id(),
            message_id,
        )
        if key in self._claimed_inputs:
            return False
        self._claimed_inputs[key] = None
        if len(self._claimed_inputs) > MAX_CLAIMED_MENU_INPUTS:
            self._claimed_inputs.pop(next(iter(self._claimed_inputs)))
        return True

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
        if context.active_ticket_count:
            self._cancelled_queued_tokens.add(context.token)
            self._cancelled_active_tickets[context.token] = context.active_ticket_count
        self._close_queued_conversation(context)

    def _finish_cancelled_ticket(self, token: str) -> None:
        remaining = self._cancelled_active_tickets.get(token, 0) - 1
        if remaining > 0:
            self._cancelled_active_tickets[token] = remaining
            return
        self._cancelled_active_tickets.pop(token, None)
        self._cancelled_queued_tokens.discard(token)

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
            return self._versions.get(session_id) == version and content_check(event)

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
