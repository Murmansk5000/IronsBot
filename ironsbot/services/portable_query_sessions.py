# SPDX-License-Identifier: MIT
"""Platform-neutral single-process selection sessions for query results."""

from __future__ import annotations

from dataclasses import replace
from time import monotonic
from typing import TYPE_CHECKING, Any, TypeVar, cast, overload

from ironsbot.core.interactive_prompts import PromptChoice
from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.selection import SelectionMenuItem, format_selection_menu
from ironsbot.core.semantic_requests import (
    SemanticRequest,
    SemanticRequestSource,
    SemanticTarget,
)
from ironsbot.services.portable_interactions import (
    PortableInteractions,
    check_current_interaction,
)
from ironsbot.services.portable_query_types import (
    MenuSelect,  # noqa: F401 - public compatibility
    PortableMenuSpec,
    PortableQueryOperation,  # noqa: F401 - public compatibility
    PortableQuerySessionError,
    PortableResponseReservation,  # noqa: F401 - public compatibility
    PortableTextInputSpec,
    QueryOperationSpec,
    QuerySelect,
    _PendingSelection,
    _PendingTextInput,
    _SessionKey,
    _UntypedMenuSelect,
)
from ironsbot.services.portable_reply import PortableReply
from ironsbot.services.portable_session_state import _MENU_ACCESS, PortableSessionState

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Literal

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.semantic_requests import ActionDefinition
    from ironsbot.services.seer.query_result import QueryResult

_T = TypeVar("_T")
_SESSION_EXPIRED_MESSAGE = "查询会话已超时，请重新发送原指令。"


class PortableQuerySessions(PortableSessionState):
    """Own one active interaction template per actor and conversation."""

    def __init__(
        self, *, ttl_seconds: float = 120.0, now: Callable[[], float] = monotonic
    ) -> None:
        super().__init__(ttl_seconds=ttl_seconds, now=now)
        self.interactions = PortableInteractions(self)

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
            if spec.contextual_select is not None:
                return await spec.contextual_select(cast("_T", value), _context)
            return await spec.select(cast("_T", value))

        result = (
            await spec.contextual_search(argument, context)
            if spec.contextual_search
            else await spec.search(argument)
        )
        return self._present(
            context,
            result,
            select=select_untyped,
            prompt_title=spec.prompt_title,
            not_found_message=spec.not_found_message,
            keep_open=spec.keep_open,
            action=spec.action,
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
            keep_open=False,
        )
        assert message is not None
        return message

    def offer_menu(
        self,
        context: MessageInputContext,
        spec: PortableMenuSpec[_T],
    ) -> OutboundMessage:
        """Offer a custom numeric menu through the shared session store."""
        check_current_interaction()

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

        def can_select(value: object, ctx: MessageInputContext) -> bool:
            return spec.can_select is None or spec.can_select(cast("_T", value), ctx)

        key = self._key(context)
        if not spec.choices:
            self._pending.pop(key, None)
            return spec.prompt
        session = self._new_session(
            context,
            tuple(
                PromptChoice(
                    (
                        spec.choice_keys[index - 1].strip()
                        if spec.choice_keys
                        else str(index)
                    ),
                    spec.labels[index - 1] if spec.labels else f"选项 {index}",
                    frozenset(
                        {
                            spec.choice_keys[index - 1].strip()
                            if spec.choice_keys
                            else str(index)
                        }
                    )
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
            choice_ids=tuple(
                choice.id for choice in session.choices if choice.id != "0"
            ),
            select=select_untyped,
            prompt_title="",
            not_found_message="",
            expires_at=session.expires_at,
            shared_select=(
                shared_select_untyped
                if spec.shared_select is not None
                else select_untyped
                if spec.shareable
                else None
            ),
            semantic_request=(
                semantic_request_untyped if spec.semantic_request is not None else None
            ),
            shared_choice_ids=frozenset(
                session.choices[index - 1].id
                for index in (
                    range(1, len(spec.choices) + 1)
                    if spec.shareable
                    else spec.shared_choice_indexes
                )
            ),
            keep_open=spec.keep_open,
            exit_message=spec.exit_message,
            access=spec.access or self._access(context),
            can_select=can_select,
            owner_context=context,
            invalid_choice_message=spec.invalid_choice_message,
            claim_unknown_numeric=spec.claim_unknown_numeric,
        )
        return replace(spec.prompt, prompt=session)

    def offer_text_input(
        self,
        context: MessageInputContext,
        spec: PortableTextInputSpec,
    ) -> OutboundMessage:
        check_current_interaction()
        key = self._key(context)
        session = self._new_session(context, ())
        self._pending[key] = _PendingTextInput(
            submit=spec.submit,
            expires_at=self._now() + self._ttl_seconds,
            exit_message=spec.exit_message,
            session=session,
        )
        return replace(spec.prompt, prompt=session)

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
        owner = self.quoted_owner(context) or context
        text = self._quoted_selection_text(text, owner, context)
        if self._is_direct_command_over_selection(
            text, context, self._pending.get(key)
        ):
            return None
        if text.strip() == "0":
            pending = self._pending.get(key)
            if pending is not None or key in self._reservations:
                self.discard(context)
                return OutboundMessage.from_text(
                    pending.exit_message if pending else "已退出查询。"
                )
            return None
        owner = self.quoted_owner(context)
        if owner is not None and self._key(owner) != key:
            return await self.select_shared(
                text, owner, context, allow_deferred=allow_deferred
            )
        if not self._accepts_anchor(self._pending.get(key), context):
            return None
        reservation = self._active_reservation(key)
        if reservation is not None and reservation.accepts(text):
            await self._wait_for_reservation(key, reservation)
            check_current_interaction()
        return await self._select_pending(text, context, allow_deferred=allow_deferred)

    async def _select_pending(
        self, text: str, context: MessageInputContext, *, allow_deferred: bool
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
            return await self._select_text(text, pending, context)
        if pending is None:
            return None
        choice = pending.session.choice_from_action(text)
        if choice is None:
            choice = pending.session.choice_from_text(text)
        if choice is None:
            if text.strip().isdigit():
                return OutboundMessage.from_text(
                    pending.invalid_choice_message
                    or f"序号无效，输入 1～{len(pending.choices)}，或输入 0 退出。"
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

    async def select_shared(
        self,
        text: str,
        owner: MessageInputContext,
        responder: MessageInputContext,
        *,
        allow_deferred: bool = False,
    ) -> OutboundMessage | PortableReply | None:
        """Execute a quoted choice without transferring direct menu ownership."""

        pending = self._shared_pending(owner, responder)
        if pending is None:
            return None
        text = self._quoted_selection_text(text, owner, responder)
        choice = self._selection_choice(pending, text)
        if choice is None or choice.id not in pending.shared_choice_ids:
            return None
        value = pending.choices[_choice_index(pending, choice)]
        if (pending.access is not None and not pending.access(responder)) or (
            pending.can_select is not None and not pending.can_select(value, responder)
        ):
            return OutboundMessage.from_text("当前会话没有使用该选项的权限。")
        assert pending.shared_select is not None
        access_token = _MENU_ACCESS.set(pending.access)
        try:
            result = await pending.shared_select(value, responder)
        finally:
            _MENU_ACCESS.reset(access_token)
        if isinstance(result, PortableReply) and not allow_deferred:
            raise PortableQuerySessionError.deferred_result_not_enabled()
        if isinstance(result, (PortableReply, OutboundMessage)):
            return result
        return self._present(
            responder,
            result,
            select=pending.shared_select,
            prompt_title=pending.prompt_title,
            not_found_message=pending.not_found_message,
            keep_open=True,
            action=pending.action,
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
        text = self._quoted_selection_text(text, owner, context)
        choice = self._selection_choice(pending, text)
        if choice is None or choice.id == "0" or pending.semantic_request is None:
            return None
        if (
            responder is not None
            and responder.message.actor != owner.message.actor
            and choice.id not in pending.shared_choice_ids
        ):
            return None
        value = pending.choices[_choice_index(pending, choice)]
        if (pending.access is not None and not pending.access(context)) or (
            pending.can_select is not None and not pending.can_select(value, context)
        ):
            return None
        return pending.semantic_request(
            pending.choices[_choice_index(pending, choice)], context
        )

    async def _select_choice(
        self,
        context: MessageInputContext,
        *,
        key: _SessionKey,
        pending: _PendingSelection,
        choice: PromptChoice,
        allow_deferred: bool,
    ) -> OutboundMessage | PortableReply | None:
        if choice.id == "0":
            self._pending.pop(key, None)
            return OutboundMessage.from_text(pending.exit_message)
        value = pending.choices[_choice_index(pending, choice)]
        if (pending.access is not None and not pending.access(context)) or (
            pending.can_select is not None and not pending.can_select(value, context)
        ):
            return OutboundMessage.from_text("当前会话没有使用该选项的权限。")
        if not pending.keep_open:
            self._pending.pop(key, None)
        access_token = _MENU_ACCESS.set(pending.access)
        try:
            result = await pending.select(value, context)
        finally:
            _MENU_ACCESS.reset(access_token)
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
            keep_open=pending.keep_open,
            action=pending.action,
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

    def _present(  # noqa: PLR0913 - explicit interaction state transition
        self,
        context: MessageInputContext,
        result: QueryResult[Any],
        *,
        select: _UntypedMenuSelect,
        prompt_title: str,
        not_found_message: str | None,
        keep_open: bool,
        action: ActionDefinition | None = None,
    ) -> OutboundMessage | None:
        check_current_interaction()
        key = self._key(context)
        if result.message:
            if not keep_open:
                self._pending.pop(key, None)
            return OutboundMessage.from_text(result.message)
        if result.reply is not None:
            if not keep_open:
                self._pending.pop(key, None)
            return result.reply.to_outbound()
        if not result.choices:
            if not keep_open:
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
            choice_ids=tuple(
                choice.id for choice in session.choices if choice.id != "0"
            ),
            select=select,
            prompt_title=prompt_title,
            not_found_message=not_found_message,
            expires_at=session.expires_at,
            keep_open=keep_open,
            shared_select=select,
            shared_choice_ids=frozenset(
                choice.id for choice in session.choices if choice.id != "0"
            ),
            access=self._access(context),
            owner_context=context,
            action=action,
            claim_unknown_numeric=True,
            semantic_request=(
                lambda value, _ctx: SemanticRequest(
                    action=action,
                    target=_query_target(value, result),
                    source=SemanticRequestSource.MENU,
                )
            )
            if action
            else None,
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


def _query_target(value: object, result: QueryResult[Any]) -> SemanticTarget:
    for choice in result.choices:
        if choice.value == value:
            target = getattr(choice, "semantic_target", None)
            if isinstance(target, SemanticTarget):
                return target
            return SemanticTarget(key=str(value), display=choice.name)
    return SemanticTarget(key=str(value), display=str(value))


def _choice_index(pending: _PendingSelection, choice: PromptChoice) -> int:
    try:
        return pending.choice_ids.index(choice.id)
    except ValueError as error:
        msg = "prompt choice does not belong to the pending menu"
        raise PortableQuerySessionError(msg) from error
