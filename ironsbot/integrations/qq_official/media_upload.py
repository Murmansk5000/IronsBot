# SPDX-License-Identifier: MIT
"""QQ Official media materialization around the Tencent SDK uploader."""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from qqbot_agent_sdk.constants import MEDIA_TYPE_IMAGE

if TYPE_CHECKING:
    from typing import Literal

    from ironsbot.integrations.qq_official.message_rendering import (
        QQOfficialImagePayload,
    )


class TencentMediaUploader(Protocol):
    async def upload(
        self,
        chat_type: str,
        chat_id: str,
        source: str,
        file_type: int,
        file_name: str | None = None,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class QQOfficialMediaUpload:
    uploader: TencentMediaUploader
    temporary_root: Path

    async def upload_image(
        self,
        scope: Literal["c2c", "group"],
        target_id: str,
        payload: QQOfficialImagePayload,
    ) -> str:
        if payload.url is not None:
            return await self.uploader.upload(
                scope,
                target_id,
                payload.url,
                MEDIA_TYPE_IMAGE,
                payload.filename,
            )
        if payload.content is None:
            msg = "QQ Official image payload has no source"
            raise ValueError(msg)

        path = await asyncio.to_thread(
            _write_temporary_media,
            self.temporary_root,
            payload.filename,
            payload.content,
        )
        try:
            return await self.uploader.upload(
                scope,
                target_id,
                str(path),
                MEDIA_TYPE_IMAGE,
                payload.filename,
            )
        finally:
            await asyncio.to_thread(path.unlink, missing_ok=True)


def _write_temporary_media(root: Path, filename: str, content: bytes) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix
    descriptor, raw_path = tempfile.mkstemp(
        prefix="ironsbot-qq-",
        suffix=suffix,
        dir=root,
    )
    path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path
