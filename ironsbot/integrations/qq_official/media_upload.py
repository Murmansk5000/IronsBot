# SPDX-License-Identifier: MIT
"""QQ Official media materialization around the Tencent SDK uploader."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import tempfile
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from qqbot_agent_sdk.constants import MEDIA_TYPE_IMAGE

from ironsbot.core.delivery_attempt import (
    MediaReuseBatch,
    controlled_delivery,
    delivery_unit,
    media_reuse_batch,
)
from ironsbot.integrations.qq_official.delivery_diagnostics import delivery_phase

if TYPE_CHECKING:
    from typing import Literal

    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.integrations.qq_official.message_rendering import (
        QQOfficialImagePayload,
    )

logger = logging.getLogger(__name__)
MediaKey = tuple[str, str, str]


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
    account_id: str = ""
    spawn: TaskSpawner | None = None
    _batches: dict[MediaReuseBatch, dict[MediaKey, asyncio.Task[str]]] = field(
        default_factory=dict, init=False, compare=False, repr=False
    )

    async def upload_image(
        self,
        scope: Literal["c2c", "group"],
        target_id: str,
        payload: QQOfficialImagePayload,
    ) -> str:
        async with (
            delivery_phase("upload_prepare")
            if controlled_delivery.get()
            else nullcontext()
        ):
            batch = media_reuse_batch.get()
            if batch is None or self.spawn is None:
                return await self._upload_image(scope, target_id, payload)
            fingerprint = await asyncio.to_thread(_media_fingerprint, payload)
            key = (scope, fingerprint, Path(payload.filename).suffix.lower())
            uploads = self._batches.get(batch)
            if uploads is None:
                uploads = {}
                self._batches[batch] = uploads

                async def close() -> None:
                    tasks = self._batches.pop(batch, {}).values()
                    for pending in tasks:
                        if not pending.done():
                            pending.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)

                batch.cleanups.append(close)
            task = uploads.get(key)
            reused = task is not None
            if task is None:
                coroutine = self._upload_image(scope, target_id, payload)
                try:
                    task = self.spawn(coroutine, name="qq-shared-media-upload")
                except BaseException:
                    coroutine.close()
                    raise
                uploads[key] = task
            logger.info(
                "QQ upload reuse: unit=%s account=%s scope=%s media=%s reused=%s",
                delivery_unit.get(),
                self.account_id or "isolated-client",
                scope,
                fingerprint[:12],
                reused,
            )
            try:
                return await asyncio.shield(task)
            except BaseException:
                failed = task.done() and (
                    task.cancelled() or task.exception() is not None
                )
                if failed and uploads.get(key) is task:
                    uploads.pop(key)
                raise

    async def _upload_image(
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


def _media_fingerprint(payload: QQOfficialImagePayload) -> str:
    if payload.url is not None:
        return hashlib.sha256(b"url:" + payload.url.encode()).hexdigest()
    if payload.content is None:
        msg = "QQ Official image payload has no source"
        raise ValueError(msg)
    return hashlib.sha256(payload.content).hexdigest()
