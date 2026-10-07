# SPDX-License-Identifier: MIT
"""FIFO interaction admission, including delivery of deferred menu results."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol
from weakref import WeakValueDictionary

from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.semantic_requests import semantic_request_scope
from ironsbot.services.operations.request_feedback import acknowledged_request_scope
from ironsbot.services.portable_reply import PortableReply
from ironsbot.services.seer.data_queries import DataQueryImageReply

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.platform import ActorRef
    from ironsbot.core.response_admission import ResponseAdmissionDecision
    from ironsbot.core.semantic_requests import SemanticRequest
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_query_types import _SessionKey
    from ironsbot.services.portable_reply import PortableOperation


class MenuRequestAdmission(Protocol):
    def admit(
        self, *, actor: ActorRef, request: SemanticRequest
    ) -> ResponseAdmissionDecision: ...
    def finish(self, token: object) -> None: ...
    def release(self, token: object) -> None: ...


class MenuCooldown(Protocol):
    def admit(
        self, *, actor: ActorRef, command_id: str
    ) -> ResponseAdmissionDecision: ...
    def finish(self, token: object) -> None: ...
    def release(self, token: object) -> None: ...


@dataclass(slots=True)
class _Generation:
    expires_at: float
    active: bool = True


_CURRENT: ContextVar[_Generation | None] = ContextVar("menu_generation", default=None)
_MAX_EARLY_INPUT_LENGTH = 4


@dataclass(slots=True)
class _SelectionRun:
    lock: asyncio.Lock
    service: MenuRequestAdmission | None
    admission: ResponseAdmissionDecision | None
    cooldown: MenuCooldown | None = None
    cooldown_admission: ResponseAdmissionDecision | None = None
    acquired: bool = False
    handed_off: bool = False
    failed: bool = False

    @property
    def denied(self) -> bool:
        return any(
            decision is not None and not decision.allowed
            for decision in (self.admission, self.cooldown_admission)
        )

    def feedback(self) -> PortableReply | None:
        denied = next(
            (
                d
                for d in (self.admission, self.cooldown_admission)
                if d is not None and not d.allowed
            ),
            None,
        )
        value = denied.feedback if denied else None
        return as_portable_reply(value) if value else None

    def release(self) -> None:
        if self.service is not None and self.admission is not None:
            self.service.release(self.admission.token)
        if self.cooldown is not None and self.cooldown_admission is not None:
            self.cooldown.release(self.cooldown_admission.token)
        if self.acquired:
            self.lock.release()
            self.acquired = False

    def wrap(self, reply: PortableReply) -> PortableReply:
        def failed() -> None:
            self.failed = True
            reply.delivery_failed()

        def finished() -> None:
            try:
                if reply.on_finished is not None:
                    reply.on_finished()
            finally:
                self.complete()
                self.release()

        self.handed_off = True
        return replace(reply, on_delivery_failed=failed, on_finished=finished)

    def complete(self) -> None:
        if self.failed:
            return
        for service, decision in (
            (self.service, self.admission),
            (self.cooldown, self.cooldown_admission),
        ):
            if service is not None and decision is not None:
                service.finish(decision.token)
        self.admission = None
        self.cooldown_admission = None

    def admit_cooldown(self, actor: ActorRef, request: SemanticRequest | None) -> None:
        if (
            self.cooldown is not None
            and request is not None
            and request.action.cooldown_key
        ):
            self.cooldown_admission = self.cooldown.admit(
                actor=actor,
                command_id=request.action.cooldown_key,
            )


def check_current_interaction() -> None:
    generation = _CURRENT.get()
    if generation is not None and not generation.active:
        raise asyncio.CancelledError


def as_portable_reply(
    result: OutboundMessage | PortableReply | DataQueryImageReply | str,
) -> PortableReply:
    if isinstance(result, PortableReply):
        return result
    if isinstance(result, DataQueryImageReply):
        return PortableReply(result.to_outbound())
    if isinstance(result, str):
        return PortableReply(OutboundMessage.from_text(result))
    return PortableReply(result)


class PortableInteractions:
    def __init__(self, sessions: PortableQuerySessions) -> None:
        self.sessions = sessions
        self._locks: WeakValueDictionary[_SessionKey, asyncio.Lock] = (
            WeakValueDictionary()
        )
        self._generations: dict[_SessionKey, _Generation] = {}
        self.request_service: MenuRequestAdmission | None = None
        self.cooldown: MenuCooldown | None = None

    def invalidate(self, context: MessageInputContext) -> None:
        self.invalidate_key(self.sessions._key(context))

    def invalidate_key(self, key: _SessionKey) -> None:
        generation = self._generations.pop(key, None)
        if generation is not None:
            generation.active = False

    def _generation(self, key: _SessionKey) -> _Generation:
        now = self.sessions._now()
        for existing, generation in tuple(self._generations.items()):
            if generation.expires_at <= now:
                self.invalidate_key(existing)
        return self._generations.setdefault(
            key, _Generation(now + self.sessions._ttl_seconds)
        )

    def _admit(
        self, text: str, context: MessageInputContext
    ) -> ResponseAdmissionDecision | None:
        if self.request_service is None:
            return None
        owner = self.sessions.quoted_owner(context) or context
        request = self.sessions.resolve_semantic_request(text, owner, context)
        return (
            self.request_service.admit(actor=context.message.actor, request=request)
            if request is not None
            else None
        )

    def _admit_ready(
        self, run: _SelectionRun, text: str, context: MessageInputContext
    ) -> None:
        if run.admission is None:
            run.admission = self._admit(text, context)
        if not run.denied:
            owner = self.sessions.quoted_owner(context) or context
            run.admit_cooldown(
                context.message.actor,
                self.sessions.resolve_semantic_request(text, owner, context),
            )

    async def select(
        self, text: str, context: MessageInputContext
    ) -> PortableReply | None:
        if not self.sessions.recognizes_response(text, context):
            return None
        # Exit must not wait behind a slow query. Its generation is invalidated now.
        if text.strip() == "0":
            result = await self.sessions.select(text, context, allow_deferred=True)
            return as_portable_reply(result) if result is not None else None
        lock = self._locks.get(self.sessions._key(context))
        if lock is not None and lock.locked():
            return self._queued_selection(text, context)
        return await self._select_nonzero(text, context)

    def _queued_selection(
        self, text: str, context: MessageInputContext
    ) -> PortableReply:
        async def run_acknowledged() -> PortableReply | None:
            with acknowledged_request_scope():
                return await self._select_nonzero(text, context)

        task = asyncio.ensure_future(run_acknowledged())
        handed_off = False

        async def continue_selection() -> PortableReply | None:
            nonlocal handed_off
            result = await task
            handed_off = True
            return result

        def discard_queued() -> None:
            if handed_off:
                return
            if not task.done():
                task.cancel()
                return
            if not task.cancelled() and task.exception() is None:
                result = task.result()
                if result is not None:
                    result.delivery_failed()
                    if result.on_finished is not None:
                        result.on_finished()

        return PortableReply(
            OutboundMessage.from_text(
                f"⏳ 已收到选项 {text.strip()}，已加入队列，完成后会直接发送结果。"
            ),
            continuation=continue_selection,
            on_delivery_failed=discard_queued,
        )

    async def _select_nonzero(
        self, text: str, context: MessageInputContext
    ) -> PortableReply | None:
        key = self.sessions._key(context)
        generation = self._generation(key)
        run = _SelectionRun(
            self._locks.setdefault(key, asyncio.Lock()),
            self.request_service,
            self._admit(text, context),
            self.cooldown,
        )
        if run.denied:
            return run.feedback()
        try:
            await run.lock.acquire()
            run.acquired = True
            if not generation.active:
                return None
            generation_token = _CURRENT.set(generation)
            try:
                reservation = self.sessions._active_reservation(key)
                if reservation is not None and reservation.accepts(text):
                    await self.sessions._wait_for_reservation(key, reservation)
                check_current_interaction()
                self._admit_ready(run, text, context)
                if run.denied:
                    return run.feedback()
                owner = self.sessions.quoted_owner(context) or context
                request = self.sessions.resolve_semantic_request(text, owner, context)
                with semantic_request_scope(request, actor=context.message.actor):
                    result = await self.sessions.select(
                        text, context, allow_deferred=True
                    )
            finally:
                _CURRENT.reset(generation_token)
            if result is None:
                return None
            reply = as_portable_reply(result)
            generation.expires_at = self.sessions._now() + self.sessions._ttl_seconds
            return run.wrap(
                self._guard(
                    reply, generation, request=request, actor=context.message.actor
                )
            )
        except BaseException:
            if generation.active:
                self.sessions.discard(context)
            raise
        finally:
            if not run.handed_off:
                run.release()

    async def execute(
        self, operation: PortableOperation, text: str, context: MessageInputContext
    ) -> PortableReply | None:
        self.invalidate(context)
        reservation = self.sessions.reserve_responses(context, accepts_menu_input)
        generation = self._generation(self.sessions._key(context))
        generation_token = _CURRENT.set(generation)
        try:
            result = await operation(text, context)
        except BaseException:
            reservation.cancel()
            if generation.active:
                self.invalidate(context)
            raise
        finally:
            _CURRENT.reset(generation_token)
        if result is None:
            reservation.cancel()
            return None
        return self._guard(reservation.guard(as_portable_reply(result)), generation)

    def _guard(
        self,
        reply: PortableReply,
        generation: _Generation,
        *,
        request: SemanticRequest | None = None,
        actor: ActorRef | None = None,
    ) -> PortableReply:
        async def follow_up() -> OutboundMessage:
            assert reply.follow_up is not None
            token = _CURRENT.set(generation)
            try:
                check_current_interaction()
                with semantic_request_scope(request, actor=actor):
                    return await reply.follow_up()
            finally:
                _CURRENT.reset(token)

        return replace(
            reply,
            is_current=lambda: (
                generation.active
                and generation.expires_at > self.sessions._now()
                and (reply.is_current is None or reply.is_current())
            ),
            follow_up=follow_up if reply.follow_up is not None else None,
        )


def accepts_menu_input(text: str) -> bool:
    value = text.strip()
    return value.isdigit() or (
        0 < len(value) <= _MAX_EARLY_INPUT_LENGTH
        and value.isascii()
        and value[0].isalpha()
        and (len(value) == 1 or value[1:].isdigit())
    )
