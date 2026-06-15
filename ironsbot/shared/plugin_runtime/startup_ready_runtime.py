# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

from nonebot import get_driver

from ironsbot.shared.plugin_runtime.startup_ready import run_registered_startup_checks

_startup_ready_runtime_state = {"registered": False}


def _setup_startup_ready_runtime(driver: Any) -> None:
    if _startup_ready_runtime_state["registered"]:
        return

    driver.on_bot_connect(run_registered_startup_checks)
    _startup_ready_runtime_state["registered"] = True


def setup_startup_ready_runtime() -> None:
    _setup_startup_ready_runtime(get_driver())


__all__ = ["setup_startup_ready_runtime"]
