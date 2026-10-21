# SPDX-License-Identifier: MIT
"""Single-attempt SDK hooks for durable callers; other callers retain SDK policy."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlsplit

import httpx
from qqbot_agent_sdk.media_loader import ChunkedUploader, MediaUploader
from typing_extensions import override

from ironsbot.core.delivery_attempt import controlled_delivery, delivery_unit
from ironsbot.integrations.qq_official.delivery_diagnostics import delivery_phase
from ironsbot.integrations.qq_official.media_diagnostics import (
    log_media_metadata,
    log_upload_parts,
)

COS_PUT_TIMEOUT = httpx.Timeout(connect=15.0, read=60.0, write=60.0, pool=30.0)
COS_PART_DEADLINE_SECONDS = 300.0
logger = logging.getLogger(__name__)


class ControlledMediaUploader(MediaUploader):
    async def _url_upload_with_retry(
        self, chat_type: str, chat_id: str, msg: Any
    ) -> dict[str, Any]:
        if not controlled_delivery.get():
            return await super()._url_upload_with_retry(chat_type, chat_id, msg)
        async with delivery_phase("upload_prepare"):
            if chat_type == "c2c":
                return await self._api.upload_c2c_file(chat_id, msg)
            return await self._api.upload_group_file(chat_id, msg)

    async def _local_upload(
        self,
        chat_type: str,
        chat_id: str,
        file_path: str,
        file_type: int,
        file_name: str,
    ) -> str:
        if not controlled_delivery.get():
            return await super()._local_upload(
                chat_type, chat_id, file_path, file_type, file_name
            )
        await asyncio.to_thread(log_media_metadata, file_path)
        chunked = _SingleAttemptChunked(self._api, self._http_client, self._log_tag)
        result = await chunked.upload(
            chat_type, chat_id, file_path, file_type, file_name
        )
        if not result.token:
            msg = "Upload completed without a file token"
            raise ValueError(msg)
        return result.token


class _SingleAttemptChunked(ChunkedUploader):
    @override
    async def _prepare(
        self,
        chat_type: str,
        target_id: str,
        file_type: int,
        file_name: str,
        file_size: int,
        hashes: dict[str, str],
    ) -> Any:
        async with delivery_phase("upload_prepare"):
            prepared = await super()._prepare(
                chat_type, target_id, file_type, file_name, file_size, hashes
            )
            log_upload_parts(file_size, prepared)
            return prepared

    @override
    async def _put_to_presigned_url(
        self, url: str, data: bytes, part_index: int, total_parts: int
    ) -> None:
        logger.info(
            "QQ COS PUT started: unit=%s part=%d/%d bytes=%d host=%s "
            "connect_timeout=%.1f read_timeout=%.1f write_timeout=%.1f "
            "pool_timeout=%.1f total_deadline=%.1f",
            delivery_unit.get(),
            part_index,
            total_parts,
            len(data),
            urlsplit(url).hostname,
            COS_PUT_TIMEOUT.connect,
            COS_PUT_TIMEOUT.read,
            COS_PUT_TIMEOUT.write,
            COS_PUT_TIMEOUT.pool,
            COS_PART_DEADLINE_SECONDS,
        )
        async with delivery_phase(f"cos_put[{part_index}/{total_parts}]"):
            response = await asyncio.wait_for(
                self._http.put(
                    url,
                    content=data,
                    headers={"Content-Length": str(len(data))},
                    timeout=COS_PUT_TIMEOUT,
                ),
                timeout=COS_PART_DEADLINE_SECONDS,
            )
            response.raise_for_status()
            logger.info(
                "QQ COS PUT accepted: unit=%s part=%d/%d bytes=%d "
                "http_status=%d trace_id=%s",
                delivery_unit.get(),
                part_index,
                total_parts,
                len(data),
                response.status_code,
                response.headers.get("x-cos-request-id")
                or response.headers.get("x-tps-trace-id"),
            )

    @override
    async def _part_finish_with_retry(
        self,
        chat_type: str,
        target_id: str,
        upload_id: str,
        part_index: int,
        block_size: int,
        md5: str,
        retry_timeout: float,
    ) -> None:
        async with delivery_phase("upload_confirm"):
            if chat_type == "c2c":
                await self._api.upload_c2c_part_finish(
                    target_id, upload_id, part_index, block_size, md5
                )
            else:
                await self._api.upload_group_part_finish(
                    target_id, upload_id, part_index, block_size, md5
                )

    async def _complete(self, chat_type: str, target_id: str, upload_id: str) -> Any:
        async with delivery_phase("upload_complete"):
            if chat_type == "c2c":
                return await self._api.complete_c2c_upload(target_id, upload_id)
            return await self._api.complete_group_upload(target_id, upload_id)
