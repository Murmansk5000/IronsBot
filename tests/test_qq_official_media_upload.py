from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from qqbot_agent_sdk.constants import MEDIA_TYPE_IMAGE

from ironsbot.integrations.qq_official.media_upload import QQOfficialMediaUpload
from ironsbot.integrations.qq_official.message_rendering import QQOfficialImagePayload

if TYPE_CHECKING:
    from typing import Literal


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
        self.calls.append(
            (chat_type, chat_id, source, file_type, file_name, content)
        )
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
