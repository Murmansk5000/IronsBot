# SPDX-License-Identifier: MIT
"""Bounded volatile delivery claims for explicitly in-process runtimes."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from time import monotonic
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.core.inbound_claims import InboundMessageKey


@dataclass(slots=True)
class MemoryInboundMessageClaims:
    retention_seconds: float = 86400.0
    capacity: int = 100000
    clock: Callable[[], float] = field(default=monotonic, repr=False)
    _claims: OrderedDict[InboundMessageKey, float] = field(
        default_factory=OrderedDict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if self.retention_seconds <= 0 or self.capacity <= 0:
            msg = "inbound claim retention and capacity must be positive"
            raise ValueError(msg)

    async def claim(self, key: InboundMessageKey) -> bool:
        now = self.clock()
        while self._claims and next(iter(self._claims.values())) <= now:
            self._claims.popitem(last=False)
        if key in self._claims:
            return False
        self._claims[key] = now + self.retention_seconds
        if len(self._claims) > self.capacity:
            self._claims.popitem(last=False)
        return True
