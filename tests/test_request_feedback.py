import asyncio

import pytest

from ironsbot.services.operations.request_feedback import (
    current_request_feedback,
    request_feedback_scope,
    send_request_feedback,
)


@pytest.mark.asyncio
async def test_nested_scope_restores_parent_after_failure() -> None:
    messages: list[tuple[str, bool]] = []

    async def send(label: str, *, queued: bool) -> None:
        messages.append((label, queued))

    assert current_request_feedback() is None
    with request_feedback_scope("outer", send) as outer:
        with (
            pytest.raises(ValueError, match="operation failed"),
            request_feedback_scope("inner", send),
        ):
            await send_request_feedback(queued=True)
            message = "operation failed"
            raise ValueError(message)
        assert current_request_feedback() is outer
        with request_feedback_scope("silent", None):
            assert current_request_feedback() is None
            await send_request_feedback(queued=False)
        await send_request_feedback(queued=False)

    assert current_request_feedback() is None
    await send_request_feedback(queued=True)
    assert messages == [("inner", True), ("outer", False)]


@pytest.mark.asyncio
async def test_concurrent_sends_share_one_feedback_claim() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    messages: list[tuple[str, bool]] = []

    async def send(label: str, *, queued: bool) -> None:
        messages.append((label, queued))
        started.set()
        await release.wait()

    with request_feedback_scope("shared", send):
        first = asyncio.create_task(send_request_feedback(queued=True))
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            await send_request_feedback(queued=False)
        finally:
            release.set()
            await first

    assert messages == [("shared", True)]


@pytest.mark.asyncio
async def test_failed_sender_is_logged_without_repeated_attempts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    attempts: list[tuple[str, bool]] = []

    async def send(label: str, *, queued: bool) -> None:
        attempts.append((label, queued))
        message = "transport unavailable"
        raise RuntimeError(message)

    with request_feedback_scope("query", send):
        await send_request_feedback(queued=True)
        await send_request_feedback(queued=False)

    assert attempts == [("query", True)]
    assert "transport unavailable" in caplog.text


@pytest.mark.asyncio
async def test_explicit_feedback_does_not_consume_unrelated_context() -> None:
    messages: list[tuple[str, bool]] = []

    async def send(label: str, *, queued: bool) -> None:
        messages.append((label, queued))

    with request_feedback_scope("earlier", send) as earlier:
        assert earlier is not None
    with request_feedback_scope("current", send):
        await send_request_feedback(queued=True, feedback=earlier)
        await send_request_feedback(queued=False)

    assert messages == [("earlier", True), ("current", False)]
