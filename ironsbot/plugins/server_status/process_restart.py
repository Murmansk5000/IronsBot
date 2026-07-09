# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import os
import signal

from nonebot import logger

PARENT_EXIT_WAIT_SECONDS = 5.0


async def restart_bot_process() -> None:
    current_pid = os.getpid()
    parent_pid = os.getppid()
    target_pid = parent_pid if parent_pid > 0 else current_pid
    logger.warning(
        "admin requested bot restart: current_pid={}, target_pid={}",
        current_pid,
        target_pid,
    )
    os.kill(target_pid, signal.SIGTERM)
    if target_pid != current_pid:
        await asyncio.sleep(PARENT_EXIT_WAIT_SECONDS)
        logger.warning(
            "bot restart parent did not stop current worker yet; "
            "sending SIGTERM to current_pid={}",
            current_pid,
        )
        os.kill(current_pid, signal.SIGTERM)
