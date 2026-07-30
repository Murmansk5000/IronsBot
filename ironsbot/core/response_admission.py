# SPDX-License-Identifier: MIT
"""Shared admission results and one-cycle feedback state."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResponseAdmissionDecision:
    """The common result shape for a response admission policy."""

    allowed: bool
    token: object | None = None
    feedback: str | None = None


@dataclass(slots=True)
class FeedbackOnce:
    """Return one feedback message for one execution or cooldown cycle."""

    sent: bool = False

    def take(self, message: str) -> str | None:
        if self.sent:
            return None
        self.sent = True
        return message
