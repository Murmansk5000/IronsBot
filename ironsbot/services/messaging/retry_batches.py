# SPDX-License-Identifier: MIT
"""Bounded, sequential batches shared by proactive delivery callers."""

from __future__ import annotations

import asyncio
from math import ceil
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

T = TypeVar("T")


def retry_batch_size(count: int, limit: int, divisor: int, *, retry: bool) -> int:
    size = max(1, ceil(count / divisor)) if retry else max(1, count)
    return min(size, limit) if limit > 0 else size


async def run_delivery_batches(
    targets: Sequence[T],
    send: Callable[[T], Awaitable[None]],
    *,
    batch_size: int,
) -> None:
    for start in range(0, len(targets), batch_size):
        await asyncio.gather(
            *(send(target) for target in targets[start : start + batch_size])
        )
