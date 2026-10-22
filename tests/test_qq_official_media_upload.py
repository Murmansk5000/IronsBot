from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from qqbot_agent_sdk.constants import MEDIA_TYPE_IMAGE

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.core.delivery_attempt import reuse_media_uploads
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
