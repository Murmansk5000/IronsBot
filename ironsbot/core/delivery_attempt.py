# SPDX-License-Identifier: MIT
"""Per-call delivery controls, propagated without coupling ports to adapters."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from secrets import token_hex
from time import monotonic

_LOGGER = logging.getLogger(__name__)

# A durable caller owns retries; adapters must not start another retry loop.
controlled_delivery: ContextVar[bool] = ContextVar("controlled_delivery", default=False)
delivery_unit: ContextVar[str] = ContextVar("delivery_unit", default="")
delivery_round: ContextVar[int] = ContextVar("delivery_round", default=0)
delivery_execution: ContextVar[tuple[str, str] | None] = ContextVar(
    "delivery_execution", default=None
)


@dataclass(eq=False, slots=True)
class DeliveryProgress:
    """Mutable evidence shared with child tasks for exactly one send."""

    phase: str | None = None
    known_pre_submit: bool = False
    may_have_submitted: bool = False
    deadline: float | None = None
    consumer_progress: list["DeliveryProgress"] | None = None
    _closed: bool = field(default=False, init=False)

    @property
    def closed(self) -> bool:
        return (
            self._closed
            or (self.deadline is not None and monotonic() >= self.deadline)
            or (
                self.consumer_progress is not None
                and all(consumer.closed for consumer in self.consumer_progress)
            )
        )

    def close(self) -> None:
        self._closed = True

    @property
    def safe_to_retry(self) -> bool:
        return self.known_pre_submit and not self.may_have_submitted


delivery_progress: ContextVar[DeliveryProgress | None] = ContextVar(
    "delivery_progress", default=None
)


@dataclass(eq=False, slots=True)
class MediaReuseBatch:
    """Own transport resources only for one active delivery, including retries."""

    cleanups: list[Callable[[], Awaitable[None]]] = field(default_factory=list)
    diagnostic_id: str = field(default_factory=lambda: token_hex(6))


media_reuse_batch: ContextVar[MediaReuseBatch | None] = ContextVar(
    "media_reuse_batch", default=None
)


async def _run_media_cleanups(batch: MediaReuseBatch) -> BaseException | None:
    first_error: BaseException | None = None
    for close in batch.cleanups:
        try:
            await close()
        except (Exception, asyncio.CancelledError) as error:  # noqa: BLE001, PERF203
            if isinstance(error, Exception):
                _LOGGER.error(  # noqa: TRY400 - cleanup errors can contain signed URLs
                    "Media upload cleanup failed: batch=%s exception=%s",
                    batch.diagnostic_id,
                    type(error).__name__,
                )
            if first_error is None:
                first_error = error
    # Return failures so cancelled shield wrappers cannot log their unsafe text.
    return first_error


async def _finish_media_cleanups(batch: MediaReuseBatch) -> None:
    # This future is scoped and joined here, including repeated cancellation.
    cleanup = asyncio.ensure_future(_run_media_cleanups(batch))
    cancellation: asyncio.CancelledError | None = None
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError as error:  # noqa: PERF203
            if cancellation is None:
                cancellation = error
    error = cleanup.result()
    if cancellation is not None:
        raise cancellation
    if error is not None:
        raise error


@asynccontextmanager
async def reuse_media_uploads() -> AsyncIterator[None]:
    if media_reuse_batch.get() is not None:
        yield
        return
    batch = MediaReuseBatch()
    marker = media_reuse_batch.set(batch)
    try:
        yield
    finally:
        media_reuse_batch.reset(marker)
        await _finish_media_cleanups(batch)


@contextmanager
def execution_account(account_id: str) -> Iterator[None]:
    marker = delivery_unit.set(delivery_unit.get() + f" execution_app={account_id}")
    try:
        yield
    finally:
        delivery_unit.reset(marker)
