# SPDX-License-Identifier: MIT
"""Account-scoped menu ownership, delivery anchors, and input reservations."""

from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from dataclasses import replace
from secrets import token_urlsafe
from time import monotonic
from typing import TYPE_CHECKING

from ironsbot.core.interactive_prompts import PromptChoice, PromptSession
from ironsbot.services.portable_query_types import (
    PortableQuerySessionError,
    PortableResponseReservation,
    _PendingResponseReservation,
    _PendingSelection,
    _PendingTextInput,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.outbound import OutboundMessage, SendResult
    from ironsbot.services.portable_interactions import PortableInteractions
    from ironsbot.services.portable_query_types import (
        MenuAccess,
        PendingResponseCheck,
        _SessionKey,
    )

_LOGGER = logging.getLogger(__name__)
_MENU_ACCESS: ContextVar[MenuAccess | None] = ContextVar("menu_access", default=None)


class PortableSessionState:
    interactions: PortableInteractions

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
        self.access_resolver: Callable[[MessageInputContext], MenuAccess] | None = None
        self.explicit_command: Callable[[MessageInputContext], bool] | None = None

    def record_delivery(
        self, context: MessageInputContext, message: OutboundMessage, result: SendResult
    ) -> None:
        """Only the delivered menu itself may supply a reply anchor."""
        if message.prompt is None:
            return
        key = self._key(context)
        pending = self._pending.get(key)
        if pending is None or pending.session.id != message.prompt.id:
            return
        if not result.delivered:
            self.discard(context)
            return
        self._pending[key] = replace(
            pending,
            anchor_ids=(
                frozenset((str(result.message_id), *result.reply_anchor_ids))
                if result.message_id
                else frozenset()
            ),
        )
        _LOGGER.info(
            "portable menu activated: namespace=query platform=%s bot=%s "
            "conversation=%s session=%s message_id=%s",
            context.message.conversation.platform.value,
            key[2],
            context.message.conversation.kind,
            pending.session.id,
            result.message_id,
        )

    def menu_anchor(self, context: MessageInputContext) -> str | None:
        pending = self._pending.get(self._key(context))
        return (
            next(iter(pending.anchor_ids), None)
            if isinstance(pending, _PendingSelection)
            else None
        )

    def quoted_owner(self, context: MessageInputContext) -> MessageInputContext | None:
        if not context.is_reply:
            return None
        own = self._pending.get(self._key(context))
        if (
            isinstance(own, _PendingSelection)
            and own.expires_at > self._now()
            and context.message.reply_to_id in own.anchor_ids
        ):
            return own.owner_context
        for key in tuple(self._pending):
            self._drop_expired(key)
            pending = self._pending.get(key)
            if (
                isinstance(pending, _PendingSelection)
                and key[1:] == self._key(context)[1:]
                and context.message.reply_to_id in pending.anchor_ids
                and pending.owner_context is not None
            ):
                return pending.owner_context
        return None

    def discard_prompt(self, context: MessageInputContext, prompt_id: str) -> None:
        pending = self._pending.get(self._key(context))
        if isinstance(pending, _PendingSelection) and pending.session.id == prompt_id:
            self.discard(context)

    def record_proactive_delivery(
        self, context: MessageInputContext, message: OutboundMessage, result: SendResult
    ) -> None:
        if message.prompt is None or not result.delivered:
            return
        pending = self._pending.get(self._key(context))
        if (
            not isinstance(pending, _PendingSelection)
            or pending.session.id != message.prompt.id
        ):
            return
        actual = replace(context, execution_identity=result.execution_identity)
        self._pending.pop(self._key(context), None)
        self.discard(actual)
        self._pending[self._key(actual)] = replace(pending, owner_context=actual)
        self.record_delivery(actual, message, result)

    def _access(self, context: MessageInputContext) -> MenuAccess | None:
        return _MENU_ACCESS.get() or (
            self.access_resolver(context) if self.access_resolver else None
        )

    @staticmethod
    def _accepts_anchor(
        pending: _PendingSelection | _PendingTextInput | None,
        context: MessageInputContext,
    ) -> bool:
        return not context.is_reply or (
            pending is not None and context.message.reply_to_id in pending.anchor_ids
        )

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
        if text.strip() == "0" and (key in self._pending or key in self._reservations):
            return True
        owner = self.quoted_owner(context)
        if owner is not None and self._key(owner) != key:
            return self.recognizes_shared_response(text, owner, context)
        if (
            context.is_reply
            and text.strip() != "0"
            and not self._accepts_anchor(self._pending.get(key), context)
        ):
            return False
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
        return (
            isinstance(pending, _PendingTextInput)
            and not (self.explicit_command and self.explicit_command(context))
        ) or (
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
        self.interactions.invalidate(context)
        self._cancel_reservation(key)
        self._pending.pop(key, None)

    def active_prompt(self, context: MessageInputContext) -> PromptSession | None:
        key = self._key(context)
        self._drop_expired(key)
        pending = self._pending.get(key)
        return pending.session if isinstance(pending, _PendingSelection) else None

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
        return choice is not None and choice.id in pending.shared_choice_ids

    def _drop_expired(self, key: _SessionKey) -> None:
        pending = self._pending.get(key)
        if pending is not None and pending.expires_at <= self._now():
            self._pending.pop(key, None)
            self.interactions.invalidate_key(key)

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
            or (pending.claim_unknown_numeric and text.strip().isdigit())
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
            or self._key(responder)[2] != self._key(owner)[2]
        ):
            return None
        key = self._key(owner)
        self._drop_expired(key)
        pending = self._pending.get(key)
        if not isinstance(pending, _PendingSelection):
            return None
        if responder.message.reply_to_id not in pending.anchor_ids:
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
        return (
            context.message.actor,
            context.message.conversation,
            context.execution_identity.account_id
            if context.execution_identity
            else context.message.conversation.account_id or "",
        )

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
