from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.message_origin import current_message_origin, message_origin
from ironsbot.core.outbound import OutboundMessage, RemoteImagePart, SendResult
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.bilibili.image_messages import iter_dynamic_image_messages
from ironsbot.services.messaging.image_collage import ImageCollageService, PreparedImage
from ironsbot.services.portable_query_sessions import (
    PortableMenuSpec,
    PortableQuerySessions,
)
from ironsbot.services.portable_reply import PortableReply, deliver_portable_reply

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence


def _context(platform: Platform) -> MessageInputContext:
    return MessageInputContext(
        IncomingMessageRef(
            platform,
            ActorRef(platform, "caller"),
            ConversationRef(platform, "group", "group"),
            "message",
            "query",
        ),
        mentions_bot=True,
    )


def _menu(
    sessions: PortableQuerySessions, context: MessageInputContext, title: str
) -> OutboundMessage:
    return sessions.offer_menu(
        context,
        PortableMenuSpec(
            choices=(title,),
            select=AsyncMock(return_value=OutboundMessage.from_text(title)),
            prompt=OutboundMessage.from_text(title),
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("mode", ["follow_up", "continuation", "stream", "nested"])
@pytest.mark.parametrize("replacement", [False, True])
async def test_all_deferred_business_cannot_install_a_menu_after_exit_or_replacement(
    platform: Platform, mode: str, *, replacement: bool
) -> None:
    context = _context(platform)
    sessions = PortableQuerySessions()
    started, release = asyncio.Event(), asyncio.Event()

    async def work() -> OutboundMessage:
        started.set()
        await release.wait()
        return _menu(sessions, context, "obsolete")

    async def stream() -> AsyncGenerator[OutboundMessage, None]:
        yield await work()

    async def continuation() -> PortableReply:
        if mode == "nested":
            return PortableReply(OutboundMessage.from_text("child"), follow_up=work)
        return PortableReply(await work())

    async def execute(text: str, context: MessageInputContext) -> PortableReply:
        del text, context
        return PortableReply(
            OutboundMessage.from_text("initial"),
            follow_up=work if mode == "follow_up" else None,
            continuation=continuation if mode in {"continuation", "nested"} else None,
            additional_stream=stream if mode == "stream" else None,
        )

    with message_origin(context):
        reply = await sessions.interactions.execute(execute, "query", context)
    assert reply is not None
    send = AsyncMock(return_value=SendResult(delivered=True, message_id="receipt"))
    delivering = asyncio.create_task(deliver_portable_reply(reply, send))
    await asyncio.wait_for(started.wait(), timeout=2)
    sessions.discard(context)
    latest = _menu(sessions, context, "latest") if replacement else None
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await delivering
    assert sessions.active_prompt(context) == (latest.prompt if latest else None)
    assert all(
        "obsolete" not in str(call.args[0].parts) for call in send.await_args_list
    )
    assert current_message_origin() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_rejected_bilibili_image_joins_pending_collage_tasks(
    platform: Platform, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(platform)
    slow_started, slow_closed = asyncio.Event(), asyncio.Event()
    urls = ("https://example.test/fast.png", "https://example.test/slow.png")
    collage = ImageCollageService(AsyncMock(), Mock(return_value=b"image"))
    monkeypatch.setattr(
        ImageCollageService,
        "_download_assets",
        AsyncMock(return_value=tuple((url, None, None) for url in urls)),
    )

    async def prepare(
        _self: ImageCollageService,
        group: Sequence[tuple[str | bytes, bytes]],
        *,
        animated: bool | None,
    ) -> tuple[PreparedImage, ...]:
        del animated
        if group[0][0] == urls[0]:
            await slow_started.wait()
            return (PreparedImage(url=urls[0]),)
        slow_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            slow_closed.set()
        return ()

    monkeypatch.setattr(ImageCollageService, "_prepare_group", prepare)
    item = {
        "modules": {
            "module_dynamic": {
                "major": {
                    "opus": {
                        "pics": [{"url": url} for url in urls],
                    }
                }
            }
        }
    }
    with message_origin(context):
        reply = PortableReply(
            OutboundMessage.from_text("initial"),
            additional_stream=lambda: iter_dynamic_image_messages(item, collage),
        )

    async def send(message: OutboundMessage) -> SendResult:
        if any(isinstance(part, RemoteImagePart) for part in message.parts):
            return SendResult(delivered=False, error_code="rejected")
        return SendResult(delivered=True, message_id="receipt")

    assert not await asyncio.wait_for(deliver_portable_reply(reply, send), timeout=2)
    assert slow_started.is_set()
    assert slow_closed.is_set()
    assert reply.outcome.failed


@pytest.mark.asyncio
async def test_stream_factory_failure_still_uses_the_shared_error_reply() -> None:
    failure = RuntimeError("private diagnostic")
    on_error = AsyncMock(
        return_value=OutboundMessage.from_text("safe", request_succeeded=False)
    )
    reply = PortableReply(
        OutboundMessage.from_text("initial"),
        additional_stream=Mock(side_effect=failure),
        on_operation_error=on_error,
    )
    send = AsyncMock(return_value=SendResult(delivered=True, message_id="receipt"))
    assert not await deliver_portable_reply(reply, send)
    on_error.assert_awaited_once_with(failure)
    assert [call.args[0] for call in send.await_args_list] == [
        OutboundMessage.from_text("initial"),
        OutboundMessage.from_text("safe", request_succeeded=False),
    ]


@pytest.mark.asyncio
async def test_stream_close_failure_marks_failure_and_finishes_once() -> None:
    async def stream() -> AsyncGenerator[OutboundMessage, None]:
        try:
            yield OutboundMessage.from_text("first")
        finally:
            raise RuntimeError

    finished = Mock()
    reply = PortableReply(
        OutboundMessage.from_text("initial"),
        additional_stream=stream,
        on_finished=finished,
    )
    send = AsyncMock(
        side_effect=[
            SendResult(delivered=True, message_id="initial"),
            SendResult(delivered=False, error_code="rejected"),
        ]
    )
    with pytest.raises(RuntimeError):
        await deliver_portable_reply(reply, send)
    assert reply.outcome.failed
    finished.assert_called_once()


async def _send_stream_part(
    message: OutboundMessage, *, outcome: str, current: list[bool]
) -> SendResult:
    if message == OutboundMessage.from_text("first"):
        if outcome == "raise":
            raise RuntimeError
        if outcome == "cancelled":
            raise asyncio.CancelledError
        if outcome == "stale":
            current[0] = False
        if outcome == "rejected":
            return SendResult(delivered=False, error_code="rejected")
    return SendResult(delivered=True, message_id="receipt")


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize(
    "outcome",
    [
        "success",
        "rejected",
        "raise",
        "cancelled",
        "stale",
        "business_failure",
        "stream_failure",
    ],
)
async def test_stream_closes_before_completion_on_every_delivery_outcome(
    platform: Platform, outcome: str
) -> None:
    context = _context(platform)
    closed: list[MessageInputContext | None] = []
    current = [True]
    advanced = Mock()
    completed_snapshots: list[tuple[MessageInputContext | None, ...]] = []
    finished = Mock(side_effect=lambda: completed_snapshots.append(tuple(closed)))

    async def stream() -> AsyncGenerator[OutboundMessage, None]:
        try:
            yield OutboundMessage.from_text(
                "first", request_succeeded=outcome != "business_failure"
            )
            advanced()
            if outcome == "stream_failure":
                raise RuntimeError
            yield OutboundMessage.from_text("last")
        finally:
            await asyncio.sleep(0)
            closed.append(current_message_origin())

    with message_origin(context):
        reply = PortableReply(
            OutboundMessage.from_text("initial"),
            additional_stream=stream,
            is_current=lambda: current[0],
            on_finished=finished,
            on_operation_error=AsyncMock(
                return_value=OutboundMessage.from_text(
                    "safe failure", request_succeeded=False
                )
            ),
        )

    send = partial(_send_stream_part, outcome=outcome, current=current)

    if outcome in {"raise", "cancelled"}:
        with pytest.raises(
            asyncio.CancelledError if outcome == "cancelled" else RuntimeError
        ):
            await deliver_portable_reply(reply, send)
    else:
        assert await deliver_portable_reply(reply, send) is (outcome == "success")
    assert closed == [context]
    assert finished.call_count == 1
    assert completed_snapshots == [(context,)]
    assert reply.outcome.failed is (outcome != "success")
    if outcome not in {"success", "stream_failure"}:
        advanced.assert_not_called()
    assert current_message_origin() is None
