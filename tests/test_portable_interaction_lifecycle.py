from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.outbound import OutboundMessage, SendResult
from ironsbot.core.response_admission import ResponseAdmissionDecision
from ironsbot.core.semantic_requests import (
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    SemanticTarget,
)
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.services.portable_query_sessions import (
    PortableMenuSpec,
    PortableQuerySessions,
)
from ironsbot.services.portable_reply import PortableReply, deliver_portable_reply
from tests.helpers.onebot_events import group_message_event

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext


def _context(
    user: int, text: str = "1", anchor: int | None = None
) -> MessageInputContext:
    return message_input_context(
        group_message_event(
            text,
            user_id=user,
            reply_message_id=anchor,
            reply_sender_user_id=1 if anchor is not None else None,
        )
    )


def _menu(
    sessions: PortableQuerySessions, context: MessageInputContext, select: Any
) -> OutboundMessage:
    message = sessions.offer_menu(
        context,
        PortableMenuSpec(
            choices=(1, 2),
            select=select,
            prompt=OutboundMessage.from_text("menu"),
            shareable=True,
            keep_open=True,
            semantic_request=lambda value, _ctx: SemanticRequest(
                ActionDefinition("test.query", "query", cooldown_key="test.query"),
                SemanticTarget(str(value), str(value)),
                SemanticRequestSource.MENU,
            ),
        ),
    )
    sessions.record_delivery(
        context, message, SendResult(delivered=True, message_id="123")
    )
    return message


async def _deliver(reply: PortableReply | None) -> None:
    assert reply is not None
    await deliver_portable_reply(
        reply, AsyncMock(return_value=SendResult(delivered=True, message_id="result"))
    )


@pytest.mark.asyncio
async def test_clone_admission_belongs_to_responder_and_denial_preserves_menu() -> None:
    sessions = PortableQuerySessions()
    owner, responder = _context(101), _context(102, anchor=123)
    select = AsyncMock(return_value=OutboundMessage.from_text("result"))
    _menu(sessions, owner, select)
    own = _menu(
        sessions,
        replace(responder, message=replace(responder.message, reply_to_id=None)),
        select,
    )
    # Use a distinct anchor for B's existing menu.
    sessions.record_delivery(
        responder, own, SendResult(delivered=True, message_id="456")
    )
    cooldown, requests = Mock(), Mock()
    requests.admit.return_value = ResponseAdmissionDecision(
        allowed=True, token="request"
    )
    cooldown.admit.return_value = ResponseAdmissionDecision(
        allowed=False, feedback="limited"
    )
    sessions.interactions.cooldown = cooldown
    sessions.interactions.request_service = requests
    await _deliver(await sessions.interactions.select("1", responder))
    assert sessions.active_prompt(responder) == own.prompt
    select.assert_not_awaited()
    requests.release.assert_called_with("request")
    cooldown.admit.assert_called_once_with(
        actor=responder.message.actor, command_id="test.query"
    )

    cooldown.admit.return_value = ResponseAdmissionDecision(
        allowed=True, token="cooldown"
    )
    await _deliver(await sessions.interactions.select("1", responder))
    assert sessions.active_prompt(responder) != own.prompt
    select.assert_awaited_once_with(1, responder)
    assert requests.admit.call_args.kwargs["actor"] == responder.message.actor
    requests.finish.assert_called_once_with("request")
    cooldown.finish.assert_called_once_with("cooldown")
    await _deliver(await sessions.interactions.select("0", owner))
    assert sessions.has_active_session(responder)


@pytest.mark.asyncio
@pytest.mark.parametrize("replace_menu", [False, True])
async def test_late_callback_cannot_resurrect_exited_or_replaced_menu(
    *, replace_menu: bool
) -> None:
    sessions = PortableQuerySessions()
    context = _context(101)
    ready, release = asyncio.Event(), asyncio.Event()

    async def opening(text: str, context: MessageInputContext) -> OutboundMessage:
        del text
        ready.set()
        await release.wait()
        return _menu(sessions, context, AsyncMock())

    old = asyncio.create_task(sessions.interactions.execute(opening, "menu", context))
    await ready.wait()
    await _deliver(await sessions.interactions.select("0", context))
    latest = _menu(sessions, context, AsyncMock()) if replace_menu else None
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await old
    assert sessions.active_prompt(context) == (latest.prompt if latest else None)


@pytest.mark.asyncio
async def test_failed_menu_delivery_releases_early_input_and_all_state() -> None:
    sessions = PortableQuerySessions()
    context = _context(101)

    async def opening(text: str, context: MessageInputContext) -> OutboundMessage:
        del text
        return _menu(sessions, context, AsyncMock())

    reply = await sessions.interactions.execute(opening, "menu", context)
    assert reply is not None
    waiting = asyncio.create_task(sessions.interactions.select("1", context))
    await asyncio.sleep(0)
    assert not await deliver_portable_reply(
        reply, AsyncMock(return_value=SendResult(delivered=False, error_code="failed"))
    )
    assert await waiting is None
    assert not sessions.recognizes_response("1", context)
    assert sessions.menu_anchor(context) is None


@pytest.mark.asyncio
async def test_progress_message_does_not_release_reserved_digits() -> None:
    sessions = PortableQuerySessions()
    context = _context(101)
    ready, release = asyncio.Event(), asyncio.Event()
    select = AsyncMock(return_value=OutboundMessage.from_text("result"))

    async def opening(text: str, context: MessageInputContext) -> PortableReply:
        del text

        async def follow_up() -> OutboundMessage:
            ready.set()
            await release.wait()
            return _menu(sessions, context, select)

        return PortableReply(OutboundMessage.from_text("progress"), follow_up=follow_up)

    reply = await sessions.interactions.execute(opening, "menu", context)
    delivery = asyncio.create_task(_deliver(reply))
    await ready.wait()
    queued = asyncio.create_task(sessions.interactions.select("2", context))
    await asyncio.sleep(0)
    assert not queued.done()
    release.set()
    await delivery
    await _deliver(await queued)
    select.assert_awaited_once_with(2, context)
