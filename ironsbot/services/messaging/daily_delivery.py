# SPDX-License-Identifier: MIT
"""Daily delivery ownership is distinct from a successful platform receipt."""

from typing import Literal, Protocol

DailyDeliveryOutcome = Literal["success", "failed", "uncertain"]


class DailyDeliveryStore(Protocol):
    def claim(self, principal: str, day: str) -> bool: ...

    def finish(
        self, principal: str, day: str, outcome: DailyDeliveryOutcome
    ) -> None: ...
