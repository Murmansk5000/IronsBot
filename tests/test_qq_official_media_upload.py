from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from qqbot_agent_sdk.constants import MEDIA_TYPE_IMAGE

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.core.delivery_attempt import (
    DeliveryProgress,
    controlled_delivery,
    delivery_progress,
    media_reuse_batch,
    reuse_media_uploads,
)
from ironsbot.integrations.qq_official.delivery_diagnostics import (
    QQDeliveryClosedError,
    delivery_phase,
)
from ironsbot.integrations.qq_official.media_upload import QQOfficialMediaUpload
from ironsbot.integrations.qq_official.message_rendering import QQOfficialImagePayload

if TYPE_CHECKING:
    from typing import Literal

TWO_UPLOADS = 2
ISOLATED_UPLOADS = 3


@dataclass(slots=True)
class _FakeUploader:
    error: Exception | None = None
    calls: list[tuple[str, str, str, int, str | None, bytes | None]] = field(
        default_factory=list
    )

    async def upload(
        self,
        chat_type: str,
        chat_id: str,
        source: str,
        file_type: int,
        file_name: str | None = None,
    ) -> str:
        path = Path(source)
        is_file = await asyncio.to_thread(path.is_file)
        content = await asyncio.to_thread(path.read_bytes) if is_file else None
        self.calls.append((chat_type, chat_id, source, file_type, file_name, content))
        if self.error is not None:
            raise self.error
        return "file-info"


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["c2c", "group"])
async def test_binary_image_uses_temporary_sdk_upload_source(
    tmp_path: Path,
    scope: Literal["c2c", "group"],
) -> None:
    uploader = _FakeUploader()
    media = QQOfficialMediaUpload(uploader, tmp_path)

    result = await media.upload_image(
        scope,
        "target",
        QQOfficialImagePayload(content=b"image", filename="preview.png"),
    )

    call = uploader.calls[0]
    assert result == "file-info"
    assert call[0:2] == (scope, "target")
    assert call[3:] == (MEDIA_TYPE_IMAGE, "preview.png", b"image")
    assert not await asyncio.to_thread(Path(call[2]).exists)


@pytest.mark.asyncio
async def test_remote_image_stays_url_based(tmp_path: Path) -> None:
    uploader = _FakeUploader()
    media = QQOfficialMediaUpload(uploader, tmp_path)
    url = "https://example.invalid/image.png"

    result = await media.upload_image(
        "group",
        "target",
        QQOfficialImagePayload(url=url),
    )

    assert result == "file-info"
    assert uploader.calls == [
        ("group", "target", url, MEDIA_TYPE_IMAGE, "ironsbot.png", None)
    ]
    children = await asyncio.to_thread(lambda: tuple(tmp_path.iterdir()))
    assert not children


@pytest.mark.asyncio
async def test_temporary_image_is_removed_when_sdk_upload_fails(tmp_path: Path) -> None:
    uploader = _FakeUploader(error=RuntimeError("upload failed"))
    media = QQOfficialMediaUpload(uploader, tmp_path)

    with pytest.raises(RuntimeError, match="upload failed"):
        await media.upload_image(
            "c2c",
            "target",
            QQOfficialImagePayload(content=b"image", filename="preview.png"),
        )

    assert not await asyncio.to_thread(Path(uploader.calls[0][2]).exists)


@pytest.mark.asyncio
async def test_concurrent_groups_reuse_upload_but_new_batch_uploads_again(
    tmp_path: Path,
) -> None:
    uploader = _FakeUploader()
    media = QQOfficialMediaUpload(
        uploader, tmp_path, account_id="test-app-a", spawn=TaskOwner().create
    )
    payload = QQOfficialImagePayload(content=b"shared-image")

    async with reuse_media_uploads():
        tokens = await asyncio.gather(
            *(media.upload_image("group", f"group-{n}", payload) for n in range(12))
        )
        assert tokens == ["file-info"] * 12
        assert len(uploader.calls) == 1
        assert len(media._batches) == 1
    assert not media._batches
    async with reuse_media_uploads():
        await media.upload_image("group", "group-new", payload)
    assert len(uploader.calls) == TWO_UPLOADS
    assert not await asyncio.to_thread(lambda: list(tmp_path.iterdir()))


@pytest.mark.asyncio
async def test_accounts_scopes_and_different_images_never_share_tokens(
    tmp_path: Path,
) -> None:
    first, second = _FakeUploader(), _FakeUploader()
    owner = TaskOwner()
    a = QQOfficialMediaUpload(
        first, tmp_path, account_id="test-app-a", spawn=owner.create
    )
    b = QQOfficialMediaUpload(
        second, tmp_path, account_id="test-app-b", spawn=owner.create
    )
    payload = QQOfficialImagePayload(content=b"image-one")
    async with reuse_media_uploads():
        await asyncio.gather(
            a.upload_image("group", "group-a", payload),
            a.upload_image("group", "group-b", payload),
            b.upload_image("group", "group-c", payload),
            a.upload_image("c2c", "user-a", payload),
            a.upload_image(
                "group", "group-a", QQOfficialImagePayload(content=b"image-two")
            ),
        )
    assert len(first.calls) == ISOLATED_UPLOADS
    assert len(second.calls) == 1


@pytest.mark.asyncio
async def test_failed_upload_is_not_cached_as_success(tmp_path: Path) -> None:
    uploader = _FakeUploader(error=RuntimeError("upload failed"))
    media = QQOfficialMediaUpload(uploader, tmp_path, spawn=TaskOwner().create)
    payload = QQOfficialImagePayload(content=b"image")
    async with reuse_media_uploads():
        with pytest.raises(RuntimeError, match="upload failed"):
            await media.upload_image("group", "group-a", payload)
        uploader.error = None
        assert await media.upload_image("group", "group-b", payload) == "file-info"
    assert len(uploader.calls) == TWO_UPLOADS
    assert not media._batches
    assert not await asyncio.to_thread(lambda: list(tmp_path.iterdir()))


@dataclass(slots=True)
class _BlockedUploader:
    started: asyncio.Event = field(default_factory=asyncio.Event)
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: bool = False
    calls: int = 0

    async def upload(self, *_args: object, **_kwargs: object) -> str:
        self.calls += 1
        self.started.set()
        try:
            await self.ready.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return "shared-token"


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_cancel_other_group_upload(
    tmp_path: Path,
) -> None:
    uploader = _BlockedUploader()
    media = QQOfficialMediaUpload(uploader, tmp_path, spawn=TaskOwner().create)
    payload = QQOfficialImagePayload(content=b"image")
    async with reuse_media_uploads():
        first = asyncio.create_task(media.upload_image("group", "group-a", payload))
        await uploader.started.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(media.upload_image("group", "group-b", payload))
        uploader.ready.set()
        assert await second == "shared-token"
        assert uploader.calls == 1
        assert not uploader.cancelled
    assert not await asyncio.to_thread(lambda: list(tmp_path.iterdir()))


@pytest.mark.asyncio
async def test_batch_exit_cleans_upload_after_all_waiters_cancel(
    tmp_path: Path,
) -> None:
    uploader = _BlockedUploader()
    media = QQOfficialMediaUpload(uploader, tmp_path, spawn=TaskOwner().create)
    async with reuse_media_uploads():
        waiter = asyncio.create_task(
            media.upload_image("group", "group-a", QQOfficialImagePayload(content=b"x"))
        )
        await uploader.started.wait()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not uploader.cancelled
    assert uploader.cancelled
    assert not media._batches
    assert not await asyncio.to_thread(lambda: list(tmp_path.iterdir()))


@pytest.mark.asyncio
async def test_reuse_diagnostics_distinguish_batch_format_and_upload_origin(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    uploader = _FakeUploader()
    media = QQOfficialMediaUpload(
        uploader, tmp_path, account_id="fictional-app", spawn=TaskOwner().create
    )
    with caplog.at_level(logging.INFO):
        async with reuse_media_uploads():
            await asyncio.gather(
                media.upload_image(
                    "group",
                    "private-target-a",
                    QQOfficialImagePayload(content=b"same", filename="a.PNG"),
                ),
                media.upload_image(
                    "group",
                    "private-target-b",
                    QQOfficialImagePayload(content=b"same", filename="b.png"),
                ),
            )
    assert len(uploader.calls) == 1
    assert "reused=True" in caplog.text and "batch=" in caplog.text
    assert "format=.png" in caplog.text
    assert "upload_target=" in caplog.text and "receipt_target=" in caplog.text
    assert "private-target-a" not in caplog.text
    assert "private-target-b" not in caplog.text
    assert not media._upload_origins


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_body", [False, True])
async def test_reuse_cleanup_finishes_all_callbacks_through_repeated_cancellation(
    *, cancel_body: bool
) -> None:
    body_started = asyncio.Event()
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    calls: list[str] = []

    async def first_cleanup() -> None:
        assert media_reuse_batch.get() is None
        cleanup_started.set()
        await release_cleanup.wait()
        calls.append("first")

    async def last_cleanup() -> None:
        calls.append("last")

    async def owner() -> None:
        async with reuse_media_uploads():
            batch = media_reuse_batch.get()
            assert batch is not None
            batch.cleanups.extend((first_cleanup, last_cleanup))
            body_started.set()
            if cancel_body:
                await asyncio.Event().wait()

    task = asyncio.create_task(owner())
    try:
        await asyncio.wait_for(body_started.wait(), 2)
        if cancel_body:
            task.cancel("body cancellation")
        await asyncio.wait_for(cleanup_started.wait(), 2)
        for _ in range(3):
            task.cancel("repeated cancellation")
            await asyncio.sleep(0)
            assert not task.done()
            assert calls == []
    finally:
        release_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
    assert calls == ["first", "last"]
    assert media_reuse_batch.get() is None


@pytest.mark.asyncio
async def test_reuse_cleanup_runs_remaining_callbacks_and_preserves_first_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []
    first_error = RuntimeError("https://upload.invalid/file?signature=cleanup-secret")
    last_error = ValueError("last cleanup failure")

    async def failing_cleanup() -> None:
        calls.append("first")
        raise first_error

    async def successful_cleanup() -> None:
        calls.append("middle")

    async def last_cleanup() -> None:
        calls.append("last")
        raise last_error

    with pytest.raises(RuntimeError) as caught:
        async with reuse_media_uploads():
            batch = media_reuse_batch.get()
            assert batch is not None
            batch.cleanups.extend((failing_cleanup, successful_cleanup, last_cleanup))
    assert caught.value is first_error
    assert calls == ["first", "middle", "last"]
    assert "exception=RuntimeError" in caplog.text
    assert "exception=ValueError" in caplog.text
    assert "upload.invalid" not in caplog.text
    assert "signature" not in caplog.text
    assert "last cleanup failure" not in caplog.text
    assert "Traceback" not in caplog.text
    assert media_reuse_batch.get() is None


@pytest.mark.asyncio
async def test_cancelled_cleanup_callback_does_not_skip_remaining_callbacks() -> None:
    calls: list[str] = []

    async def cancelled_cleanup() -> None:
        calls.append("cancelled")
        raise asyncio.CancelledError

    async def last_cleanup() -> None:
        calls.append("last")

    with pytest.raises(asyncio.CancelledError):
        async with reuse_media_uploads():
            batch = media_reuse_batch.get()
            assert batch is not None
            batch.cleanups.extend((cancelled_cleanup, last_cleanup))
    assert calls == ["cancelled", "last"]


@pytest.mark.asyncio
async def test_cleanup_failure_is_logged_without_losing_deferred_cancellation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    calls: list[str] = []
    failure = RuntimeError("cleanup failure during cancellation")

    async def failing_cleanup() -> None:
        cleanup_started.set()
        await release_cleanup.wait()
        calls.append("failed")
        raise failure

    async def last_cleanup() -> None:
        calls.append("last")

    async def owner() -> None:
        async with reuse_media_uploads():
            batch = media_reuse_batch.get()
            assert batch is not None
            batch.cleanups.extend((failing_cleanup, last_cleanup))

    task = asyncio.create_task(owner())
    try:
        await asyncio.wait_for(cleanup_started.wait(), 2)
        task.cancel("deferred cancellation")
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release_cleanup.set()
        with pytest.raises(asyncio.CancelledError, match="deferred cancellation"):
            await asyncio.wait_for(task, 2)
    assert calls == ["failed", "last"]
    assert "exception=RuntimeError" in caplog.text
    assert "cleanup failure during cancellation" not in caplog.text


@dataclass(slots=True)
class _ProgressAwareUploader:
    started: asyncio.Event = field(default_factory=asyncio.Event)
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    calls: int = 0
    progress: list[DeliveryProgress | None] = field(default_factory=list)

    async def upload(self, *_args: object, **_kwargs: object) -> str:
        self.calls += 1
        self.progress.append(delivery_progress.get())
        self.started.set()
        await self.ready.wait()
        # Real controlled uploads enter further transport phases after awaits.
        async with delivery_phase("upload_confirm"):
            self.progress.append(delivery_progress.get())
        return "shared-token"


def _assert_independent_shared_progress(
    uploader: _ProgressAwareUploader, first: DeliveryProgress, second: DeliveryProgress
) -> None:
    assert uploader.calls == 1
    assert len(uploader.progress) == TWO_UPLOADS
    shared = uploader.progress[0]
    assert shared is not None
    assert uploader.progress[1] is shared
    assert shared is not first
    assert shared is not second
    assert shared.deadline is None
    assert shared.consumer_progress == []


def _observe_shared_waiters(
    monkeypatch: pytest.MonkeyPatch,
    media: QQOfficialMediaUpload,
    expected: list[DeliveryProgress],
) -> asyncio.Event:
    registered = asyncio.Event()

    def shield(task: asyncio.Task[str]) -> asyncio.Future[str]:
        if media._upload_progress[task].consumer_progress == expected:
            registered.set()
        return asyncio.shield(task)

    monkeypatch.setattr(
        "ironsbot.integrations.qq_official.media_upload.asyncio",
        SimpleNamespace(
            to_thread=asyncio.to_thread, gather=asyncio.gather, shield=shield
        ),
    )
    return registered


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_first", [False, True])
async def test_shared_upload_does_not_inherit_first_waiter_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, cancel_first: bool
) -> None:
    uploader = _ProgressAwareUploader()
    media = QQOfficialMediaUpload(uploader, tmp_path, spawn=TaskOwner().create)
    payload = QQOfficialImagePayload(url="https://example.invalid/shared.png")
    first_progress = DeliveryProgress(deadline=time.monotonic() + 60)
    second_progress = DeliveryProgress(deadline=time.monotonic() + 60)
    second_registered = _observe_shared_waiters(
        monkeypatch,
        media,
        [second_progress] if cancel_first else [first_progress, second_progress],
    )

    async def wait_for_upload(target: str, progress: DeliveryProgress) -> str:
        token = delivery_progress.set(progress)
        controlled_token = controlled_delivery.set(True)
        try:
            return await media.upload_image("group", target, payload)
        finally:
            assert delivery_progress.get() is progress
            controlled_delivery.reset(controlled_token)
            delivery_progress.reset(token)

    async with reuse_media_uploads():
        first = asyncio.create_task(wait_for_upload("first", first_progress))
        second: asyncio.Task[str] | None = None
        try:
            await asyncio.wait_for(uploader.started.wait(), 2)
            assert first_progress.phase == "upload_prepare"
            assert first_progress.safe_to_retry
            first_progress.deadline = time.monotonic() - 1
            if cancel_first:
                first_progress.close()
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first
                assert first_progress.phase == "upload_prepare"
            second = asyncio.create_task(wait_for_upload("second", second_progress))
            await asyncio.wait_for(second_registered.wait(), 2)
            assert second_progress.phase == "upload_prepare"
            assert second_progress.safe_to_retry
            uploader.ready.set()
            assert await asyncio.wait_for(second, 2) == "shared-token"
            if not cancel_first:
                assert await asyncio.wait_for(first, 2) == "shared-token"
        finally:
            uploader.ready.set()
            for waiter in (first, second):
                if waiter is not None and not waiter.done():
                    waiter.cancel()
            await asyncio.gather(
                *(waiter for waiter in (first, second) if waiter is not None),
                return_exceptions=True,
            )
    assert first_progress.closed
    assert not second_progress.closed
    assert second_progress.phase is None
    _assert_independent_shared_progress(uploader, first_progress, second_progress)
    assert not media._upload_progress


@pytest.mark.asyncio
async def test_late_fingerprint_does_not_start_shared_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fingerprint_started = Event()
    fingerprint_ready = Event()
    progress = DeliveryProgress(deadline=time.monotonic() + 60)

    def fingerprint(_payload: QQOfficialImagePayload) -> str:
        fingerprint_started.set()
        if not fingerprint_ready.wait(2):
            raise TimeoutError
        return "fingerprint"

    monkeypatch.setattr(
        "ironsbot.integrations.qq_official.media_upload._media_fingerprint", fingerprint
    )
    uploader = _FakeUploader()
    media = QQOfficialMediaUpload(uploader, tmp_path, spawn=TaskOwner().create)
    token = delivery_progress.set(progress)
    controlled_token = controlled_delivery.set(True)
    try:
        async with reuse_media_uploads():
            waiter = asyncio.create_task(
                media.upload_image(
                    "group", "target", QQOfficialImagePayload(content=b"image")
                )
            )
            try:
                assert await asyncio.to_thread(fingerprint_started.wait, 2)
                assert progress.phase == "upload_prepare"
                progress.deadline = time.monotonic() - 1
            finally:
                fingerprint_ready.set()
                with pytest.raises(QQDeliveryClosedError) as caught:
                    await asyncio.wait_for(waiter, 2)
            assert caught.value.requested_phase == "upload_prepare"
            assert progress.safe_to_retry
            assert not media._batches
    finally:
        fingerprint_ready.set()
        controlled_delivery.reset(controlled_token)
        delivery_progress.reset(token)
    assert uploader.calls == []
    assert not media._upload_origins


@pytest.mark.asyncio
async def test_shared_upload_stops_next_phase_when_all_consumers_expire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploader = _ProgressAwareUploader()
    media = QQOfficialMediaUpload(uploader, tmp_path, spawn=TaskOwner().create)
    payload = QQOfficialImagePayload(url="https://example.invalid/shared.png")
    first_progress = DeliveryProgress(deadline=time.monotonic() + 60)
    second_progress = DeliveryProgress(deadline=time.monotonic() + 60)
    both_registered = _observe_shared_waiters(
        monkeypatch, media, [first_progress, second_progress]
    )

    async def wait_for_upload(target: str, progress: DeliveryProgress) -> str:
        token = delivery_progress.set(progress)
        controlled_token = controlled_delivery.set(True)
        try:
            return await media.upload_image("group", target, payload)
        finally:
            controlled_delivery.reset(controlled_token)
            delivery_progress.reset(token)

    async with reuse_media_uploads():
        first = asyncio.create_task(wait_for_upload("first", first_progress))
        second: asyncio.Task[str] | None = None
        try:
            await asyncio.wait_for(uploader.started.wait(), 2)
            shared = uploader.progress[0]
            assert shared is not None
            second = asyncio.create_task(wait_for_upload("second", second_progress))
            await asyncio.wait_for(both_registered.wait(), 2)
            assert not shared.closed
            first_progress.deadline = time.monotonic() - 1
            assert not shared.closed
            second_progress.deadline = time.monotonic() - 1
            assert shared.closed
            assert first_progress.phase == second_progress.phase == "upload_prepare"
            uploader.ready.set()
            for waiter in (first, second):
                with pytest.raises(QQDeliveryClosedError) as caught:
                    await asyncio.wait_for(waiter, 2)
                assert caught.value.requested_phase == "upload_confirm"
        finally:
            uploader.ready.set()
            for waiter in (first, second):
                if waiter is not None and not waiter.done():
                    waiter.cancel()
            await asyncio.gather(
                *(waiter for waiter in (first, second) if waiter is not None),
                return_exceptions=True,
            )
    assert uploader.calls == 1
    assert len(uploader.progress) == 1  # The upload_confirm body was never entered.
    assert shared.consumer_progress == []
    assert not media._upload_progress
