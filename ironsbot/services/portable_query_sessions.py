# SPDX-License-Identifier: MIT
"""Platform-neutral single-process selection sessions for query results."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from secrets import token_urlsafe
from time import monotonic
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar, cast, overload

from ironsbot.core.interactive_prompts import PromptChoice, PromptSession
from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.selection import SelectionMenuItem, format_selection_menu
from ironsbot.services.portable_reply import PortableReply
from ironsbot.services.seer.query_result import QueryResult

if TYPE_CHECKING:
    from typing import Literal

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.platform import ActorRef, ConversationRef
    from ironsbot.core.semantic_requests import SemanticRequest

_T = TypeVar("_T")
QuerySearch = Callable[[str], Awaitable[QueryResult[_T]]]
QuerySelect = Callable[[_T], Awaitable[QueryResult[Any]]]
QueryArgumentParser = Callable[[str], str | None]
_SessionKey = tuple["ActorRef", "ConversationRef"]
_UntypedMenuSelect = Callable[
    [object, "MessageInputContext"],
    Awaitable[QueryResult[Any] | OutboundMessage | PortableReply],
]
MenuSelect = Callable[
    [_T, "MessageInputContext"], Awaitable[OutboundMessage | PortableReply]
]
MenuSemanticRequest = Callable[[_T, "MessageInputContext"], "SemanticRequest | None"]
TextSubmit = Callable[[str, "MessageInputContext"], Awaitable[OutboundMessage]]
PendingResponseCheck = Callable[[str], bool]
_SESSION_EXPIRED_MESSAGE = "查询会话已超时，请重新发送原指令。"


class PortableQueryOperation(Protocol):
    def __call__(
        self, text: str, context: MessageInputContext
    ) -> Awaitable[OutboundMessage | None]: ...


class PortableQuerySessionError(ValueError):
    @classmethod
    def invalid_ttl(cls) -> PortableQuerySessionError:
        return cls("portable query session TTL must be positive")

    @classmethod
    def deferred_result_not_enabled(cls) -> PortableQuerySessionError:
        return cls("portable deferred session result was not enabled by the caller")

    @classmethod
    def menu_label_count_mismatch(cls) -> PortableQuerySessionError:
        return cls("portable menu labels must match the choice count")

    @classmethod
    def invalid_shared_choice(cls) -> PortableQuerySessionError:
        return cls("portable shared menu choices must reference visible choices")


@dataclass(frozen=True, slots=True)
class QueryOperationSpec(Generic[_T]):
    parser: QueryArgumentParser
    search: QuerySearch[_T]
    select: QuerySelect[_T]
    prompt_title: str
    not_found_message: str | None = None


@dataclass(frozen=True, slots=True)
class PortableMenuSpec(Generic[_T]):
    choices: tuple[_T, ...]
    select: MenuSelect[_T]
    prompt: OutboundMessage
    labels: tuple[str, ...] = ()
    text_inputs: tuple[frozenset[str], ...] = ()
    shared_select: MenuSelect[_T] | None = None
    semantic_request: MenuSemanticRequest[_T] | None = None
    shared_choice_indexes: frozenset[int] = frozenset()
    keep_open: bool = False
    exit_message: str = "已退出查询。"

    def __post_init__(self) -> None:
        if self.labels and len(self.labels) != len(self.choices):
            raise PortableQuerySessionError.menu_label_count_mismatch()
        if self.text_inputs and len(self.text_inputs) != len(self.choices):
            raise ValueError("menu text inputs must match the choice count")  # noqa: TRY003
        if any(
            index < 1 or index > len(self.choices)
            for index in self.shared_choice_indexes
        ):
            raise PortableQuerySessionError.invalid_shared_choice()
        if bool(self.shared_choice_indexes) != (self.shared_select is not None):
            raise PortableQuerySessionError.invalid_shared_choice()


@dataclass(frozen=True, slots=True)
class PortableTextInputSpec:
    submit: TextSubmit
    prompt: OutboundMessage
    exit_message: str = "已退出查询。"


@dataclass(frozen=True, slots=True)
class _PendingSelection:
    session: PromptSession
    choices: tuple[object, ...]
    select: _UntypedMenuSelect
    prompt_title: str
    not_found_message: str | None
    expires_at: float
    shared_select: _UntypedMenuSelect | None = None
    semantic_request: (
        Callable[[object, "MessageInputContext"], "SemanticRequest | None"] | None
    ) = None
    shared_choice_ids: frozenset[str] = frozenset()
    keep_open: bool = False
    exit_message: str = "已退出查询。"


@dataclass(frozen=True, slots=True)
class _PendingTextInput:
    submit: TextSubmit
    expires_at: float
    exit_message: str


@dataclass(slots=True)
class _PendingResponseReservation:
    token: object
    accepts: PendingResponseCheck
    ready: asyncio.Event
    expires_at: float


@dataclass(frozen=True, slots=True)
class PortableResponseReservation:
    """Hold early replies until the operation's first prompt is delivered."""

    _owner: PortableQuerySessions
    _key: _SessionKey
    _token: object

    def release(self) -> None:
        self._owner._finish_reservation(self._key, self._token, delivered=True)

    def cancel(self) -> None:
        self._owner._finish_reservation(self._key, self._token, delivered=False)

    def guard(self, reply: PortableReply) -> PortableReply:
        """Release waiting input only after the guarded reply is delivered."""

        def delivered() -> None:
            if reply.on_delivered is not None:
                reply.on_delivered()
            self.release()

        def failed() -> None:
            try:
                if reply.on_delivery_failed is not None:
                    reply.on_delivery_failed()
            finally:
                self.cancel()

        return replace(
            reply,
            on_delivered=delivered,
            on_delivery_failed=failed,
        )


class PortableQuerySessions:
    """Own one active interaction template per actor and conversation."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 120.0,
        now: Callable[[], float] = monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise PortableQuerySessionError.invalid_ttl()
        self._ttl_seconds = ttl_seconds
        self._now = now
        self._pending: dict[_SessionKey, _PendingSelection | _PendingTextInput] = {}
        self._reservations: dict[_SessionKey, _PendingResponseReservation] = {}

    def reserve_responses(
        self,
        context: MessageInputContext,
        accepts: PendingResponseCheck,
    ) -> PortableResponseReservation:
        """Reserve one actor/conversation while its first prompt is loading."""

        key = self._key(context)
        self._cancel_reservation(key)
        self._pending.pop(key, None)
        token = object()
        self._reservations[key] = _PendingResponseReservation(
            token=token,
            accepts=accepts,
            ready=asyncio.Event(),
            expires_at=self._now() + self._ttl_seconds,
        )
        return PortableResponseReservation(self, key, token)

    def recognizes_response(self, text: str, context: MessageInputContext) -> bool:
        key = self._key(context)
        reservation = self._active_reservation(key)
        if reservation is not None and reservation.accepts(text):
            return True
        pending = self._pending.get(key)
        if pending is not None and pending.expires_at <= self._now():
            if isinstance(
                pending, _PendingSelection
            ) and self._matches_selection_response(pending, text):
                return True
            self._pending.pop(key, None)
        self._drop_expired(key)
        pending = self._pending.get(key)
        return isinstance(pending, _PendingTextInput) or (
            isinstance(pending, _PendingSelection)
            and self._matches_selection_response(pending, text)
        )

    def has_active_session(self, context: MessageInputContext) -> bool:
        key = self._key(context)
        self._drop_expired(key)
        return key in self._pending

    def discard(self, context: MessageInputContext) -> None:
        """Remove every unfinished interaction owned by this participant."""

        key = self._key(context)
        self._cancel_reservation(key)
        self._pending.pop(key, None)

    def active_prompt(self, context: MessageInputContext) -> PromptSession | None:
        key = self._key(context)
        self._drop_expired(key)
        pending = self._pending.get(key)
        return pending.session if isinstance(pending, _PendingSelection) else None

    async def begin(
        self,
        context: MessageInputContext,
        *,
        argument: str,
        spec: QueryOperationSpec[_T],
    ) -> OutboundMessage | None:
        async def select_untyped(
            value: object,
            _context: MessageInputContext,
        ) -> QueryResult[Any]:
            return await spec.select(cast("_T", value))

        result = await spec.search(argument)
        return self._present(
            context,
            result,
            select=select_untyped,
            prompt_title=spec.prompt_title,
            not_found_message=spec.not_found_message,
        )

    def offer(
        self,
        context: MessageInputContext,
        result: QueryResult[_T],
        *,
        select: QuerySelect[_T],
        prompt_title: str,
        not_found_message: str,
    ) -> OutboundMessage:
        """Present choices produced outside the standard search operation."""

        async def select_untyped(
            value: object,
            _context: MessageInputContext,
        ) -> QueryResult[Any]:
            return await select(cast("_T", value))

        message = self._present(
            context,
            result,
            select=select_untyped,
            prompt_title=prompt_title,
            not_found_message=not_found_message,
        )
        assert message is not None
        return message

    def offer_menu(
        self,
        context: MessageInputContext,
        spec: PortableMenuSpec[_T],
    ) -> OutboundMessage:
        """Offer a custom numeric menu through the shared session store."""

        async def select_untyped(
            value: object,
            selection_context: MessageInputContext,
        ) -> OutboundMessage | PortableReply:
            return await spec.select(cast("_T", value), selection_context)

        async def shared_select_untyped(
            value: object,
            selection_context: MessageInputContext,
        ) -> OutboundMessage | PortableReply:
            if spec.shared_select is None:
                raise PortableQuerySessionError.invalid_shared_choice()
            return await spec.shared_select(cast("_T", value), selection_context)

        def semantic_request_untyped(
            value: object,
            selection_context: MessageInputContext,
        ) -> SemanticRequest | None:
            if spec.semantic_request is None:
                return None
            return spec.semantic_request(cast("_T", value), selection_context)

        key = self._key(context)
        if not spec.choices:
            self._pending.pop(key, None)
            return spec.prompt
        session = self._new_session(
            context,
            tuple(
                PromptChoice(
                    str(index),
                    spec.labels[index - 1] if spec.labels else f"选项 {index}",
                    frozenset({str(index)})
                    | (
                        spec.text_inputs[index - 1] if spec.text_inputs else frozenset()
                    ),
                )
                for index in range(1, len(spec.choices) + 1)
            ),
        )
        self._pending[key] = _PendingSelection(
            session=session,
            choices=tuple(spec.choices),
            select=select_untyped,
            prompt_title="",
            not_found_message="",
            expires_at=session.expires_at,
            shared_select=(
                shared_select_untyped if spec.shared_select is not None else None
            ),
            semantic_request=(
                semantic_request_untyped if spec.semantic_request is not None else None
            ),
            shared_choice_ids=frozenset(
                str(index) for index in spec.shared_choice_indexes
            ),
            keep_open=spec.keep_open,
            exit_message=spec.exit_message,
        )
        return replace(spec.prompt, prompt=session)

    def offer_text_input(
        self,
        context: MessageInputContext,
        spec: PortableTextInputSpec,
    ) -> OutboundMessage:
        key = self._key(context)
        self._pending[key] = _PendingTextInput(
            submit=spec.submit,
            expires_at=self._now() + self._ttl_seconds,
            exit_message=spec.exit_message,
        )
        return spec.prompt

    @overload
    async def select(
        self,
        text: str,
        context: MessageInputContext,
        *,
        allow_deferred: Literal[False] = False,
    ) -> OutboundMessage | None: ...

    @overload
    async def select(
        self,
        text: str,
        context: MessageInputContext,
        *,
        allow_deferred: Literal[True],
    ) -> OutboundMessage | PortableReply | None: ...

    async def select(
        self,
        text: str,
        context: MessageInputContext,
        *,
        allow_deferred: bool = False,
    ) -> OutboundMessage | PortableReply | None:
        key = self._key(context)
        reservation = self._active_reservation(key)
        if reservation is not None and reservation.accepts(text):
            await self._wait_for_reservation(key, reservation)
        expired = self._pending.get(key)
        if expired is not None and expired.expires_at <= self._now():
            self._pending.pop(key, None)
            if isinstance(
                expired, _PendingSelection
            ) and self._matches_selection_response(expired, text):
                return OutboundMessage.from_text(_SESSION_EXPIRED_MESSAGE)
        self._drop_expired(key)
        pending = self._pending.get(key)
        if isinstance(pending, _PendingTextInput):
            self._pending.pop(key, None)
            return await self._select_text(text, pending, context)
        if pending is None:
            return None
        choice = pending.session.choice_from_action(text)
        if choice is None:
            choice = pending.session.choice_from_text(text)
        if choice is None:
            if text.strip().isdigit():
                return OutboundMessage.from_text(
                    f"序号无效，输入 1～{len(pending.choices)}，或输入 0 退出。"
                )
            return None
        return await self._select_choice(
            context,
            key=key,
            pending=pending,
            choice=choice,
            allow_deferred=allow_deferred,
        )

    async def select_action(
        self,
        action_data: str,
        context: MessageInputContext,
        *,
        allow_deferred: bool = False,
    ) -> OutboundMessage | PortableReply | None:
        key = self._key(context)
        expired = self._pending.get(key)
        if expired is not None and expired.expires_at <= self._now():
            self._pending.pop(key, None)
            if isinstance(expired, _PendingSelection) and (
                expired.session.choice_from_action(action_data) is not None
            ):
                return OutboundMessage.from_text(_SESSION_EXPIRED_MESSAGE)
        self._drop_expired(key)
        pending = self._pending.get(key)
        if not isinstance(pending, _PendingSelection):
            return None
        choice = pending.session.choice_from_action(action_data)
        if choice is None:
            return None
        return await self._select_choice(
            context,
            key=key,
            pending=pending,
            choice=choice,
            allow_deferred=allow_deferred,
        )

    def recognizes_shared_response(
        self,
        text: str,
        owner: MessageInputContext,
        responder: MessageInputContext,
    ) -> bool:
        """Recognize an explicitly shareable choice in a quoted group menu."""

        pending = self._shared_pending(owner, responder)
        if pending is None:
            return False
        choice = self._selection_choice(pending, text)
        return choice is not None and (
            choice.id == "0" or choice.id in pending.shared_choice_ids
        )

    async def select_shared(
        self,
        text: str,
        owner: MessageInputContext,
        responder: MessageInputContext,
        *,
        allow_deferred: bool = False,
    ) -> OutboundMessage | PortableReply | None:
        """Clone one shareable group menu choice for the replying member."""

        pending = self._shared_pending(owner, responder)
        if pending is None:
            return None
        choice = self._selection_choice(pending, text)
        if choice is None or (
            choice.id != "0" and choice.id not in pending.shared_choice_ids
        ):
            return None
        key = self._key(responder)
        self._cancel_reservation(key)
        expires_at = self._now() + self._ttl_seconds
        cloned = replace(
            pending,
            select=cast("_UntypedMenuSelect", pending.shared_select),
            session=replace(
                pending.session,
                actor=responder.message.actor,
                request_message_id=responder.message.message_id,
                expires_at=expires_at,
            ),
            expires_at=expires_at,
        )
        self._pending[key] = cloned
        return await self._select_choice(
            responder,
            key=key,
            pending=cloned,
            choice=choice,
            allow_deferred=allow_deferred,
        )

    def resolve_semantic_request(
        self,
        text: str,
        owner: MessageInputContext,
        responder: MessageInputContext | None = None,
    ) -> SemanticRequest | None:
        """Resolve business identity without consuming the pending choice."""

        context = responder or owner
        if responder is None or responder.message.actor == owner.message.actor:
            key = self._key(owner)
            self._drop_expired(key)
            pending = self._pending.get(key)
            if not isinstance(pending, _PendingSelection):
                return None
        else:
            pending = self._shared_pending(owner, responder)
            if pending is None:
                return None
        choice = self._selection_choice(pending, text)
        if choice is None or choice.id == "0" or pending.semantic_request is None:
            return None
        if (
            responder is not None
            and responder.message.actor != owner.message.actor
            and choice.id not in pending.shared_choice_ids
        ):
            return None
        return pending.semantic_request(pending.choices[int(choice.id) - 1], context)

    async def _select_choice(
        self,
        context: MessageInputContext,
        *,
        key: _SessionKey,
        pending: _PendingSelection,
        choice: PromptChoice,
        allow_deferred: bool,
    ) -> OutboundMessage | PortableReply | None:
        index = int(choice.id)
        if index == 0:
            self._pending.pop(key, None)
            return OutboundMessage.from_text(pending.exit_message)

        if not pending.keep_open:
            self._pending.pop(key, None)
        result = await pending.select(pending.choices[index - 1], context)
        if isinstance(result, (OutboundMessage, PortableReply)):
            if isinstance(result, PortableReply) and not allow_deferred:
                raise PortableQuerySessionError.deferred_result_not_enabled()
            if pending.keep_open and self._pending.get(key) is pending:
                expires_at = self._now() + self._ttl_seconds
                self._pending[key] = replace(
                    pending,
                    session=replace(pending.session, expires_at=expires_at),
                    expires_at=expires_at,
                )
            return result
        return self._present(
            context,
            result,
            select=pending.select,
            prompt_title=pending.prompt_title,
            not_found_message=pending.not_found_message,
        )

    @staticmethod
    async def _select_text(
        text: str,
        pending: _PendingTextInput,
        context: MessageInputContext,
    ) -> OutboundMessage:
        if text.strip() == "0":
            return OutboundMessage.from_text(pending.exit_message)
        return await pending.submit(text.strip(), context)

    def _present(
        self,
        context: MessageInputContext,
        result: QueryResult[Any],
        *,
        select: _UntypedMenuSelect,
        prompt_title: str,
        not_found_message: str | None,
    ) -> OutboundMessage | None:
        key = self._key(context)
        if result.message:
            self._pending.pop(key, None)
            return OutboundMessage.from_text(result.message)
        if result.reply is not None:
            self._pending.pop(key, None)
            return result.reply.to_outbound()
        if not result.choices:
            self._pending.pop(key, None)
            return (
                OutboundMessage.from_text(not_found_message)
                if not_found_message is not None
                else None
            )

        session = self._new_session(
            context,
            tuple(
                PromptChoice(
                    str(index),
                    choice.name,
                    frozenset({str(index)}),
                )
                for index, choice in enumerate(result.choices, start=1)
            ),
        )
        self._pending[key] = _PendingSelection(
            session=session,
            choices=tuple(choice.value for choice in result.choices),
            select=select,
            prompt_title=prompt_title,
            not_found_message=not_found_message,
            expires_at=session.expires_at,
        )
        return replace(
            OutboundMessage.from_text(
                format_selection_menu(
                    title=prompt_title,
                    items=tuple(
                        SelectionMenuItem(
                            label=(
                                f"{choice.name}（{choice.description}）"
                                if choice.description
                                else choice.name
                            ),
                            is_sub_item=choice.is_sub_choice,
                        )
                        for choice in result.choices
                    ),
                )
            ),
            prompt=session,
        )

    def _drop_expired(self, key: _SessionKey) -> None:
        pending = self._pending.get(key)
        if pending is not None and pending.expires_at <= self._now():
            self._pending.pop(key, None)

    def _active_reservation(
        self,
        key: _SessionKey,
    ) -> _PendingResponseReservation | None:
        reservation = self._reservations.get(key)
        if reservation is not None and reservation.expires_at <= self._now():
            self._finish_reservation(key, reservation.token, delivered=False)
            return None
        return reservation

    async def _wait_for_reservation(
        self,
        key: _SessionKey,
        reservation: _PendingResponseReservation,
    ) -> None:
        timeout = max(0.0, reservation.expires_at - self._now())
        try:
            await asyncio.wait_for(reservation.ready.wait(), timeout=timeout)
        except TimeoutError:
            self._finish_reservation(key, reservation.token, delivered=False)

    def _cancel_reservation(self, key: _SessionKey) -> None:
        reservation = self._reservations.get(key)
        if reservation is not None:
            self._finish_reservation(key, reservation.token, delivered=False)

    def _finish_reservation(
        self,
        key: _SessionKey,
        token: object,
        *,
        delivered: bool,
    ) -> None:
        reservation = self._reservations.get(key)
        if reservation is None or reservation.token is not token:
            return
        self._reservations.pop(key, None)
        if not delivered:
            self._pending.pop(key, None)
        reservation.ready.set()

    @staticmethod
    def _matches_selection_response(
        pending: _PendingSelection,
        text: str,
    ) -> bool:
        return (
            pending.session.choice_from_action(text) is not None
            or pending.session.choice_from_text(text) is not None
            or text.strip().isdigit()
        )

    def _shared_pending(
        self,
        owner: MessageInputContext,
        responder: MessageInputContext,
    ) -> _PendingSelection | None:
        if (
            not responder.is_reply
            or responder.message.conversation.kind != "group"
            or responder.message.conversation != owner.message.conversation
            or responder.message.actor == owner.message.actor
        ):
            return None
        key = self._key(owner)
        self._drop_expired(key)
        pending = self._pending.get(key)
        if not isinstance(pending, _PendingSelection):
            return None
        return (
            pending
            if pending.shared_choice_ids and pending.shared_select is not None
            else None
        )

    @staticmethod
    def _selection_choice(
        pending: _PendingSelection,
        text: str,
    ) -> PromptChoice | None:
        return pending.session.choice_from_action(
            text
        ) or pending.session.choice_from_text(text)

    @staticmethod
    def _key(context: MessageInputContext) -> _SessionKey:
        return context.message.actor, context.message.conversation

    def _new_session(
        self,
        context: MessageInputContext,
        choices: tuple[PromptChoice, ...],
    ) -> PromptSession:
        exit_choice = PromptChoice(
            "0",
            "退出",
            frozenset({"0", "取消"}),
        )
        return PromptSession(
            id=token_urlsafe(18),
            actor=context.message.actor,
            conversation=context.message.conversation,
            request_message_id=context.message.message_id,
            choices=(*choices, exit_choice),
            expires_at=self._now() + self._ttl_seconds,
        )


def build_query_operation(
    sessions: PortableQuerySessions,
    spec: QueryOperationSpec[_T],
) -> PortableQueryOperation:
    """Adapt one QueryResult service without duplicating its command grammar."""

    async def execute(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage | None:
        argument = spec.parser(text)
        if argument is None:
            msg = f"catalog accepted input that its query parser rejected: {text!r}"
            raise ValueError(msg)
        return await sessions.begin(
            context,
            argument=argument,
            spec=spec,
        )

    return execute
