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

if TYPE_CHECKING:
    from asyncio import TimerHandle
    from collections.abc import Callable
    from datetime import timedelta

    from nonebot.typing import T_State

    from ironsbot.runtime.in_flight_requests import InFlightRequestService
    from ironsbot.runtime.matcher_contracts import QueuedSemanticRequestResolver

TEMP_MATCHER_STATE_TOKEN_KEY = "_ironsbot_temp_matcher_state_token"
QUEUED_CONVERSATION_TOKEN_STATE_KEY = "_ironsbot_queued_conversation_token"
QUEUED_CONVERSATION_TICKET_STATE_KEY = "_ironsbot_queued_conversation_ticket"
COMMAND_COOLDOWN_TOKEN_STATE_KEY = "_ironsbot_command_cooldown_token"  # nosec B105
IN_FLIGHT_REQUEST_TOKEN_STATE_KEY = "_ironsbot_in_flight_request_token"  # nosec B105


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
    if event.user_id == event.self_id or event.reply is None:
        return False
    # The reply sender metadata is optional in OneBot events.  The tracked
    # message ID was obtained from the bot's own send result, so it is the
    # authoritative proof that this is a reply to the current bot menu.
    return getattr(event.reply, "message_id", None) == anchor.message_id


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
    group_reply_check: Callable[[Event], bool] | None
    handlers: list[Any]
    conversation_session_id: str | None = None
    menu_anchor: GroupMenuAnchor | None = None
    semantic_request_resolver: QueuedSemanticRequestResolver | None = None
    request_service: InFlightRequestService | None = None
    active: bool = True
    keep_open: bool = False
    _next_ticket: int = 0
    _active_ticket: int | None = None
    _active_request_token: object | None = None
    _waiters: deque[tuple[int, Future[bool], object | None]] = field(
        default_factory=deque
    )

    def __post_init__(self) -> None:
        if self.conversation_session_id is None:
            self.conversation_session_id = self.event_session_id

    def matches(self, event: Event) -> bool:
        if not self.active:
            return False
        if self.reply_check(event):
            return True
        return (
            self.group_reply_check is not None
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

    def update_semantic_request_resolver(
        self,
        resolver: QueuedSemanticRequestResolver | None,
    ) -> None:
        self.semantic_request_resolver = resolver

    async def acquire(self, request_token: object | None = None) -> int | None:
        if not self.active:
            self._release_request_token(request_token)
            return None
        self._next_ticket += 1
        ticket = self._next_ticket
        future: Future[bool] = get_running_loop().create_future()
        if self._active_ticket is None:
            self._active_ticket = ticket
            self._active_request_token = request_token
            future.set_result(True)
        else:
            self._waiters.append((ticket, future, request_token))
        try:
            await future
        except BaseException:
            self._waiters = deque(
                item for item in self._waiters if item[0] != ticket
            )
            self._release_request_token(request_token)
            raise
        if self.active:
            return ticket
        self._release_request_token(request_token)
        return None

    def complete(self, ticket: int) -> None:
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

    def close(self) -> None:
        self.active = False
        self.keep_open = False
        for _, future, request_token in self._waiters:
            self._release_request_token(request_token)
            if not future.done():
                future.cancel()
        self._waiters.clear()

    def _release_request_token(self, token: object | None) -> None:
        if token is not None and self.request_service is not None:
            self.request_service.release(token)


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

    def start_queued_conversation(  # noqa: PLR0913
        self,
        *,
        namespace: str,
        event_session_id: str,
        state: T_State,
        reply_check: Callable[[Event], bool],
        group_reply_check: Callable[[Event], bool] | None = None,
        handlers: list[Any],
        semantic_request_resolver: QueuedSemanticRequestResolver | None = None,
        request_service: InFlightRequestService | None = None,
        conversation_session_id: str | None = None,
        menu_anchor: GroupMenuAnchor | None = None,
    ) -> _QueuedConversation:
        key = f"{namespace}:{event_session_id}"
        if existing := self._queued_by_key.get(key):
            self._cancel_queued_conversation(existing)
        saved_state = dict(state)
        saved_state.pop(COMMAND_COOLDOWN_TOKEN_STATE_KEY, None)
        saved_state.pop(IN_FLIGHT_REQUEST_TOKEN_STATE_KEY, None)
        context = _QueuedConversation(
            token=token_urlsafe(18),
            key=key,
            namespace=namespace,
            event_session_id=event_session_id,
            state=saved_state,
            reply_check=reply_check,
            group_reply_check=group_reply_check,
            handlers=handlers,
            conversation_session_id=conversation_session_id,
            menu_anchor=menu_anchor,
            semantic_request_resolver=semantic_request_resolver,
            request_service=request_service,
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
        if context is None or not isinstance(ticket, int):
            if context is not None:
                context.keep_open = False
            if isinstance(token, str) and isinstance(ticket, int):
                self._cancelled_queued_tokens.discard(token)
            return
        if not context.active or not context.keep_open:
            self._close_queued_conversation(context)
            return
        context.keep_open = False
        context.state = dict(state)
        context.state.pop(COMMAND_COOLDOWN_TOKEN_STATE_KEY, None)
        context.state.pop(IN_FLIGHT_REQUEST_TOKEN_STATE_KEY, None)
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
