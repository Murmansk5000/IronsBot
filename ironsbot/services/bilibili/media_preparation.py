# SPDX-License-Identifier: MIT
"""Single-flight, bounded preparation of an immutable complete media manifest."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import weakref
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ironsbot.core.outbound import BinaryImagePart, OutboundMessage, RemoteImagePart
from ironsbot.services.bilibili.delivery_lifecycle import own_delivery
from ironsbot.services.bilibili.image_messages import render_dynamic_image_message
from ironsbot.services.messaging.image_collage import ImageCollageError, _original_image

if TYPE_CHECKING:
    from typing import Any

    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.services.bilibili.delivery_ledger import DynamicDeliveryLedger
    from ironsbot.services.messaging.image_collage import ImageCollageService

_LOGGER = logging.getLogger(__name__)
_FLIGHTS: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop,
    dict[tuple[str, str, str], asyncio.Task[OutboundMessage | None]],
] = weakref.WeakKeyDictionary()
_DELAYS = (2, 5, 10)
_MAX_ATTEMPTS = len(_DELAYS) + 1
_DEADLINE_SECONDS = 60


class MediaPreparationError(ImageCollageError):
    """Terminal, known-unsent preparation failure; never retry a new global budget."""


def _failure(reason: str) -> MediaPreparationError:
    return MediaPreparationError(reason)


@dataclass
class _Preparation:
    dynamic_id: str
    urls: tuple[str, ...]
    collage: ImageCollageService
    ledger: DynamicDeliveryLedger | None
    combine: bool
    fingerprint: str
    sources: dict[str, bytes] = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)
    attempts: int = 0
    diagnostics: list[str] = field(default_factory=list)

    def record(self, status: str) -> None:
        details: dict[str, object] = {
            "attempts": self.attempts,
            "elapsed_seconds": round(time.monotonic() - self.started, 3),
            "reasons": list(self.diagnostics),
            "sources": len(self.urls),
        }
        if self.ledger:
            self.ledger.finish_media_preparation(self.dynamic_id, status, details)
        _LOGGER.info(
            "Bilibili media preparation: dynamic=%s fingerprint=%s "
            "status=%s details=%s",
            self.dynamic_id,
            self.fingerprint[:12],
            status,
            details,
        )

    async def download(self, url: str, semaphore: asyncio.Semaphore) -> None:
        key = hashlib.sha256(url.encode()).hexdigest()
        if key in self.sources:
            return
        content = (
            self.ledger.load_media_source(self.dynamic_id, key) if self.ledger else None
        )
        if content is None:
            async with semaphore:
                started = time.monotonic()
                phase = "download"
                try:
                    content = await self.collage.fetch_image(
                        url, self.collage.max_source_bytes
                    )
                    phase = "check"
                    if not content:
                        raise ImageCollageError.empty_response()
                    if len(content) > self.collage.max_source_bytes:
                        raise ImageCollageError.source_too_large()
                    if self.collage.inspect_animation:
                        phase = "decode"
                        await asyncio.to_thread(self.collage.inspect_animation, content)
                except (ImageCollageError, TimeoutError, ConnectionError) as error:
                    reason = (
                        error.diagnostic_code
                        if isinstance(error, ImageCollageError)
                        else type(error).__name__
                    )
                    self.diagnostics.append(f"{phase}:{reason}")
                    _LOGGER.warning(
                        "Bilibili media source failed: dynamic=%s source=%s "
                        "phase=%s reason=%s attempt=%d elapsed=%.3f",
                        self.dynamic_id,
                        key[:12],
                        phase,
                        reason,
                        self.attempts,
                        time.monotonic() - started,
                    )
                    raise
                _LOGGER.info(
                    "Bilibili media source ready: dynamic=%s source=%s "
                    "bytes=%d elapsed=%.3f",
                    self.dynamic_id,
                    key[:12],
                    len(content),
                    time.monotonic() - started,
                )
                if self.ledger:
                    self.ledger.save_media_source(self.dynamic_id, key, content)
        self.sources[key] = content

    async def attempt(self) -> OutboundMessage | None:
        semaphore = asyncio.Semaphore(self.collage.download_concurrency)
        results = await asyncio.gather(
            *(self.download(url, semaphore) for url in dict.fromkeys(self.urls)),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result
        images = tuple(
            self.sources[hashlib.sha256(url.encode()).hexdigest()] for url in self.urls
        )
        if self.combine:
            images = tuple(dict.fromkeys(images))
        prepared = (
            await self.collage.prepare_bytes(images)
            if self.combine and len(images) > 1
            else tuple(_original_image(image) for image in images)
        )
        self.diagnostics.extend(
            image.degradation_reason for image in prepared if image.degradation_reason
        )
        message = (
            OutboundMessage(
                tuple(
                    BinaryImagePart(
                        image.content or b"", image.content_type, image.filename
                    )
                    for image in prepared
                )
            )
            if prepared
            else None
        )
        if self.ledger:
            message = self.ledger.freeze_media(self.dynamic_id, message)
        self.record(
            "degraded"
            if any(image.degradation_reason for image in prepared)
            else "complete"
        )
        return message

    async def run(self) -> OutboundMessage | None:
        while self.attempts < _MAX_ATTEMPTS:
            self.attempts, remaining = (
                self.ledger.begin_media_preparation(self.dynamic_id, self.fingerprint)
                if self.ledger
                else (
                    self.attempts + 1,
                    _DEADLINE_SECONDS - (time.monotonic() - self.started),
                )
            )
            if not self.attempts or remaining <= 0:
                break
            attempt_started = time.monotonic()
            try:
                return await asyncio.wait_for(self.attempt(), remaining)
            except (ImageCollageError, TimeoutError, ConnectionError) as error:
                retryable = (
                    isinstance(error, (TimeoutError, ConnectionError))
                    or error.retryable
                )
                self.record("retry" if retryable else "failed")
                if not retryable:
                    raise _failure("original_media_unavailable") from error
                delay = _DELAYS[min(self.attempts - 1, 2)]
                if (
                    self.attempts >= _MAX_ATTEMPTS
                    or time.monotonic() - attempt_started + delay >= remaining
                ):
                    break
                await asyncio.sleep(delay)
            except (OSError, ValueError) as error:
                self.diagnostics.append(f"source_cache:{type(error).__name__}")
                self.record("failed")
                raise _failure("frozen_source_unavailable") from error
        self.record("failed")
        raise _failure("media_preparation_budget_exhausted")

    async def run_owned(self) -> OutboundMessage | None:
        started = time.monotonic()
        while True:
            async with own_delivery(self.ledger, "media:" + self.dynamic_id) as owned:
                if owned:
                    if self.ledger:
                        found, message = self.ledger.load_media(self.dynamic_id)
                        if found:
                            return message
                    return await self.run()
            if time.monotonic() - started >= _DEADLINE_SECONDS:
                raise _failure("media_owner_wait_exhausted")
            await asyncio.sleep(0.1)


async def prepare_shared_media(  # noqa: PLR0913 - frozen identity and task ownership
    item: dict[str, Any],
    dynamic_id: str,
    collage: ImageCollageService | None,
    ledger: DynamicDeliveryLedger | None,
    *,
    combine: bool,
    spawn: TaskSpawner | None = None,
) -> OutboundMessage | None:
    if ledger:
        found, message = ledger.load_media(dynamic_id)
        if found:
            return message
    original = render_dynamic_image_message(item)
    if original is None or collage is None:
        return ledger.freeze_media(dynamic_id, original) if ledger else original
    urls = tuple(
        part.url for part in original.parts if isinstance(part, RemoteImagePart)
    )
    fingerprint = hashlib.sha256(
        (str(combine) + "\n" + "\n".join(urls)).encode()
    ).hexdigest()
    flights = _FLIGHTS.setdefault(asyncio.get_running_loop(), {})
    key = (
        str(ledger.path.resolve()) if ledger else str(id(collage)),
        dynamic_id,
        fingerprint,
    )

    task = flights.get(key)
    if task is None:
        operation = _Preparation(
            dynamic_id, urls, collage, ledger, combine, fingerprint
        ).run_owned()
        task = (
            spawn(operation, name="bilibili.media.prepare")
            if spawn
            else asyncio.ensure_future(operation)
        )
        flights[key] = task

        def finished(done: asyncio.Task[OutboundMessage | None]) -> None:
            if flights.get(key) is done:
                del flights[key]
            if not done.cancelled():
                done.exception()

        task.add_done_callback(finished)
    return await asyncio.shield(task)
