# SPDX-License-Identifier: MIT
"""Bind native driver callbacks to the application-owned lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nonebot.internal.driver import Driver

    from ironsbot.app.lifecycle import ApplicationLifecycle


@dataclass(slots=True)
class NoneBotHostBinding:
    driver: Driver
    lifecycle: ApplicationLifecycle
    _installed: bool = field(default=False, init=False)

    def install(self) -> None:
        if self._installed:
            return
        self.driver.on_startup(self.lifecycle.startup)
        self.driver.on_shutdown(self.lifecycle.shutdown)
        self._installed = True
