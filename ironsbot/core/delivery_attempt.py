# SPDX-License-Identifier: MIT
"""Per-call delivery controls, propagated without coupling ports to adapters."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

# A durable caller owns retries; adapters must not start another retry loop.
controlled_delivery: ContextVar[bool] = ContextVar("controlled_delivery", default=False)
delivery_unit: ContextVar[str] = ContextVar("delivery_unit", default="")
delivery_round: ContextVar[int] = ContextVar("delivery_round", default=0)


@contextmanager
def execution_account(account_id: str) -> Iterator[None]:
    marker = delivery_unit.set(delivery_unit.get() + f" execution_app={account_id}")
    try:
        yield
    finally:
        delivery_unit.reset(marker)
