# SPDX-License-Identifier: MIT
"""Per-call delivery controls, propagated without coupling ports to adapters."""

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

# A durable caller owns retries; adapters must not start another retry loop.
controlled_delivery: ContextVar[bool] = ContextVar("controlled_delivery", default=False)
delivery_unit: ContextVar[str] = ContextVar("delivery_unit", default="")
delivery_round: ContextVar[int] = ContextVar("delivery_round", default=0)


@dataclass(eq=False, slots=True)
class MediaReuseBatch:
    """Own transport resources only for one active delivery, including retries."""

    cleanups: list[Callable[[], Awaitable[None]]] = field(default_factory=list)


media_reuse_batch: ContextVar[MediaReuseBatch | None] = ContextVar(
    "media_reuse_batch", default=None
)


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
        for close in batch.cleanups:
            await close()


@contextmanager
def execution_account(account_id: str) -> Iterator[None]:
    marker = delivery_unit.set(delivery_unit.get() + f" execution_app={account_id}")
    try:
        yield
    finally:
        delivery_unit.reset(marker)
