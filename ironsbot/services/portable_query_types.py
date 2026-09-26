# SPDX-License-Identifier: MIT
"""Typed contracts and reservations for portable query sessions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar

from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.portable_reply import PortableReply
from ironsbot.services.seer.query_result import QueryResult

if TYPE_CHECKING:
    import asyncio

    from ironsbot.core.interactive_prompts import PromptSession
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.platform import ActorRef, ConversationRef
    from ironsbot.core.semantic_requests import ActionDefinition, SemanticRequest
    from ironsbot.services.portable_session_state import PortableSessionState

_T = TypeVar("_T")
QuerySearch = Callable[[str], Awaitable[QueryResult[_T]]]
QuerySelect = Callable[[_T], Awaitable[QueryResult[Any]]]
QueryArgumentParser = Callable[[str], str | None]
_SessionKey = tuple["ActorRef", "ConversationRef", str]
MenuAccess = Callable[["MessageInputContext"], bool]
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

    @classmethod
    def invalid_choice_keys(cls) -> PortableQuerySessionError:
        return cls(
            "portable menu choice keys must be unique, non-empty, non-zero, "
            "and match the choice count"
        )

    @classmethod
    def invalid_hidden_choices(cls) -> PortableQuerySessionError:
        return cls("hidden menu choices require explicit non-numeric keys")


@dataclass(frozen=True, slots=True)
class QueryOperationSpec(Generic[_T]):
    parser: QueryArgumentParser
    search: QuerySearch[_T]
    select: QuerySelect[_T]
    prompt_title: str
    not_found_message: str | None = None
    keep_open: bool = True
    action: ActionDefinition | None = None
    contextual_search: (
        Callable[[str, MessageInputContext], Awaitable[QueryResult[_T]]] | None
    ) = None
    contextual_select: (
        Callable[[_T, MessageInputContext], Awaitable[QueryResult[Any]]] | None
    ) = None


@dataclass(frozen=True, slots=True)
class PortableMenuSpec(Generic[_T]):
    choices: tuple[_T, ...]
    select: MenuSelect[_T]
    prompt: OutboundMessage
    labels: tuple[str, ...] = ()
    choice_keys: tuple[str, ...] = ()
    text_inputs: tuple[frozenset[str], ...] = ()
    hidden_choice_indexes: frozenset[int] = frozenset()
    shared_select: MenuSelect[_T] | None = None
    semantic_request: MenuSemanticRequest[_T] | None = None
    shared_choice_indexes: frozenset[int] = frozenset()
    shareable: bool = False
    access: MenuAccess | None = None
    can_select: Callable[[_T, MessageInputContext], bool] | None = None
    keep_open: bool = False
    exit_message: str = "已退出查询。"
    invalid_choice_message: str | None = None
    claim_unknown_numeric: bool = True

    def __post_init__(self) -> None:
        if self.labels and len(self.labels) != len(self.choices):
            raise PortableQuerySessionError.menu_label_count_mismatch()
        normalized_keys = tuple(key.strip().casefold() for key in self.choice_keys)
        if self.choice_keys and (
            len(normalized_keys) != len(self.choices)
            or any(not key or key == "0" for key in normalized_keys)
            or len(set(normalized_keys)) != len(normalized_keys)
        ):
            raise PortableQuerySessionError.invalid_choice_keys()
        if self.text_inputs and len(self.text_inputs) != len(self.choices):
            raise ValueError("menu text inputs must match the choice count")  # noqa: TRY003
        if any(
            index < 1 or index > len(self.choices)
            for index in self.hidden_choice_indexes
        ):
            raise PortableQuerySessionError.invalid_hidden_choices()
        if self.hidden_choice_indexes and (
            not self.choice_keys
            or any(
                self.choice_keys[index - 1].isdecimal()
                for index in self.hidden_choice_indexes
            )
        ):
            raise PortableQuerySessionError.invalid_hidden_choices()
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
    choice_ids: tuple[str, ...]
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
    anchor_ids: frozenset[str] = frozenset()
    access: MenuAccess | None = None
    can_select: Callable[[object, MessageInputContext], bool] | None = None
    owner_context: MessageInputContext | None = None
    action: ActionDefinition | None = None
    invalid_choice_message: str | None = None
    claim_unknown_numeric: bool = True


@dataclass(frozen=True, slots=True)
class _PendingTextInput:
    submit: TextSubmit
    expires_at: float
    exit_message: str
    session: PromptSession
    anchor_ids: frozenset[str] = frozenset()


@dataclass(slots=True)
class _PendingResponseReservation:
    token: object
    accepts: PendingResponseCheck
    ready: asyncio.Event
    expires_at: float


@dataclass(frozen=True, slots=True)
class PortableResponseReservation:
    """Hold early replies until the operation's first prompt is delivered."""

    _owner: PortableSessionState
    _key: _SessionKey
    _token: object

    def release(self) -> None:
        self._owner._finish_reservation(self._key, self._token, delivered=True)

    def cancel(self) -> None:
        self._owner._finish_reservation(self._key, self._token, delivered=False)

    def guard(self, reply: PortableReply) -> PortableReply:
        """Release waiting input only after the guarded reply is delivered."""

        aborted = False

        def delivered() -> None:
            if reply.on_delivered is not None:
                reply.on_delivered()
            if reply.follow_up is None:
                self.release()

        def failed() -> None:
            nonlocal aborted
            aborted = True
            try:
                if reply.on_delivery_failed is not None:
                    reply.on_delivery_failed()
            finally:
                self.cancel()

        def finished() -> None:
            try:
                if reply.on_finished is not None:
                    reply.on_finished()
            finally:
                if not aborted:
                    self.release()

        return replace(
            reply,
            on_delivered=delivered,
            on_delivery_failed=failed,
            on_finished=finished,
        )
