# SPDX-License-Identifier: MIT
"""Platform-neutral single-process selection sessions for query results."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from time import monotonic
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar, cast

from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.selection import SelectionMenuItem, format_selection_menu
from ironsbot.services.seer.query_result import QueryResult

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.platform import ActorRef, ConversationRef

_T = TypeVar("_T")
QuerySearch = Callable[[str], Awaitable[QueryResult[_T]]]
QuerySelect = Callable[[_T], Awaitable[QueryResult[Any]]]
QueryArgumentParser = Callable[[str], str | None]
_SessionKey = tuple["ActorRef", "ConversationRef"]
_UntypedMenuSelect = Callable[
    [object],
    Awaitable[QueryResult[Any] | OutboundMessage],
]
MenuSelect = Callable[[_T], Awaitable[OutboundMessage]]


class PortableQueryOperation(Protocol):
    def __call__(
        self, text: str, context: MessageInputContext
    ) -> Awaitable[OutboundMessage]: ...


class PortableQuerySessionError(ValueError):
    @classmethod
    def invalid_ttl(cls) -> PortableQuerySessionError:
        return cls("portable query session TTL must be positive")


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
    keep_open: bool = False
    exit_message: str = "已退出查询。"


@dataclass(frozen=True, slots=True)
class _PendingSelection:
    choices: tuple[object, ...]
    select: _UntypedMenuSelect
    prompt_title: str
    not_found_message: str
    expires_at: float
    keep_open: bool = False
    exit_message: str = "已退出查询。"


class PortableQuerySessions:
    """Own short-lived numeric selections independently of an adapter framework."""

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
        self._pending: dict[_SessionKey, _PendingSelection] = {}

    def recognizes_selection(self, text: str, context: MessageInputContext) -> bool:
        key = self._key(context)
        self._drop_expired(key)
        return key in self._pending and text.strip().isdigit()

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

        async def select_untyped(value: object) -> OutboundMessage:
            return await spec.select(cast("_T", value))

        self._pending[self._key(context)] = _PendingSelection(
            choices=tuple(spec.choices),
            select=select_untyped,
            prompt_title="",
            not_found_message="",
            expires_at=self._now() + self._ttl_seconds,
            keep_open=spec.keep_open,
            exit_message=spec.exit_message,
        )
        return spec.prompt

    async def select(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage | None:
        key = self._key(context)
        self._drop_expired(key)
        pending = self._pending.get(key)
        if pending is None or not text.strip().isdigit():
            return None
        index = int(text.strip())
        if index == 0:
            self._pending.pop(key, None)
            return OutboundMessage.from_text(pending.exit_message)
        if index > len(pending.choices):
            return OutboundMessage.from_text(
                f"序号无效，输入 1～{len(pending.choices)}，或输入 0 退出。"
            )

        if not pending.keep_open:
            self._pending.pop(key, None)
        result = await pending.select(pending.choices[index - 1])
        if isinstance(result, OutboundMessage):
            if pending.keep_open:
                self._pending[key] = replace(
                    pending,
                    expires_at=self._now() + self._ttl_seconds,
                )
            return result
        return self._present(
            context,
            result,
            select=pending.select,
            prompt_title=pending.prompt_title,
            not_found_message=pending.not_found_message,
        )

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

        self._pending[key] = _PendingSelection(
            choices=tuple(choice.value for choice in result.choices),
            select=select,
            prompt_title=prompt_title,
            not_found_message=not_found_message,
            expires_at=self._now() + self._ttl_seconds,
        )
        return OutboundMessage.from_text(
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
        )

    def _drop_expired(self, key: _SessionKey) -> None:
        pending = self._pending.get(key)
        if pending is not None and pending.expires_at <= self._now():
            self._pending.pop(key, None)

    @staticmethod
    def _key(context: MessageInputContext) -> _SessionKey:
        return context.message.actor, context.message.conversation


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
