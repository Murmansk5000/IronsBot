# SPDX-License-Identifier: MIT
"""Typed server maintenance deadlines decoded from command 41457."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class HeadlessMaintenanceEvent:
    raw_value: int
    scheduled_at: datetime


class HeadlessMaintenanceNotifier(Protocol):
    async def __call__(self, event: HeadlessMaintenanceEvent) -> None: ...
