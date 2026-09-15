# SPDX-License-Identifier: MIT
"""Platform-neutral single-process selection sessions for query results."""

from __future__ import annotations

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

_T = TypeVar("_T")
QuerySearch = Callable[[str], Awaitable[QueryResult[_T]]]
QuerySelect = Callable[[_T], Awaitable[QueryResult[Any]]]
QueryArgumentParser = Callable[[str], str | None]
_SessionKey = tuple["ActorRef", "ConversationRef"]
_UntypedMenuSelect = Callable[
    [object],
    Awaitable[QueryResult[Any] | OutboundMessage | PortableReply],
]
MenuSelect = Callable[[_T], Awaitable[OutboundMessage | PortableReply]]
TextSubmit = Callable[[str], Awaitable[OutboundMessage]]
_SESSION_EXPIRED_MESSAGE = "查询会话已超时，请重新发送原指令。"


class PortableQueryOperation(Protocol):
    def __call__(
        self, text: str, context: MessageInputContext
    ) -> Awaitable[OutboundMessage]: ...


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


@dataclass(frozen=True, slots=True)
class QueryOperationSpec(Generic[_T]):
    parser: QueryArgumentParser
    search: QuerySearch[_T]
    select: QuerySelect[_T]
    prompt_title: str
    not_found_message: str


@dataclass(frozen=True, slots=True)
class PortableMenuSpec(Generic[_T]):
    choices: tuple[_T, ...]
    select: MenuSelect[_T]
    prompt: OutboundMessage
    labels: tuple[str, ...] = ()
    text_inputs: tuple[frozenset[str], ...] = ()
    keep_open: bool = False
    exit_message: str = "已退出查询。"

    def __post_init__(self) -> None:
        if self.labels and len(self.labels) != len(self.choices):
            raise PortableQuerySessionError.menu_label_count_mismatch()
        if self.text_inputs and len(self.text_inputs) != len(self.choices):
            raise ValueError("menu text inputs must match the choice count")  # noqa: TRY003


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
    not_found_message: str
    expires_at: float
    keep_open: bool = False
    exit_message: str = "已退出查询。"


@dataclass(frozen=True, slots=True)
class _PendingTextInput:
    submit: TextSubmit
    expires_at: float
    exit_message: str


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

    def recognizes_response(self, text: str, context: MessageInputContext) -> bool:
        key = self._key(context)
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
    ) -> OutboundMessage:
        async def select_untyped(value: object) -> QueryResult[Any]:
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

        async def select_untyped(value: object) -> QueryResult[Any]:
            return await select(cast("_T", value))

        return self._present(
            context,
            result,
            select=select_untyped,
            prompt_title=prompt_title,
            not_found_message=not_found_message,
        )

    def offer_menu(
        self,
        context: MessageInputContext,
        spec: PortableMenuSpec[_T],
    ) -> OutboundMessage:
        """Offer a custom numeric menu through the shared session store."""

        async def select_untyped(
            value: object,
        ) -> OutboundMessage | PortableReply:
            return await spec.select(cast("_T", value))

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
                    frozenset({str(index)}) | (
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
            return await self._select_text(text, pending)
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

    async def _select_choice(
        self,
        context: MessageInputContext,
        *,
        key: _SessionKey,
        pending: _PendingSelection,
        choice: PromptChoice,
        allow_deferred: bool,
    ) -> OutboundMessage | PortableReply:
        index = int(choice.id)
        if index == 0:
            self._pending.pop(key, None)
            return OutboundMessage.from_text(pending.exit_message)

        if not pending.keep_open:
            self._pending.pop(key, None)
        result = await pending.select(pending.choices[index - 1])
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
    ) -> OutboundMessage:
        if text.strip() == "0":
            return OutboundMessage.from_text(pending.exit_message)
        return await pending.submit(text.strip())

    def _present(
        self,
        context: MessageInputContext,
        result: QueryResult[Any],
        *,
        select: _UntypedMenuSelect,
        prompt_title: str,
        not_found_message: str,
    ) -> OutboundMessage:
        key = self._key(context)
        if result.message:
            self._pending.pop(key, None)
            return OutboundMessage.from_text(result.message)
        if result.reply is not None:
            self._pending.pop(key, None)
            return result.reply.to_outbound()
        if not result.choices:
            self._pending.pop(key, None)
            return OutboundMessage.from_text(not_found_message)

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
                            label=choice.name,
                            detail_lines=(choice.description,)
                            if choice.description
                            else (),
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

    async def execute(text: str, context: MessageInputContext) -> OutboundMessage:
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
