# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
import os
import signal

PARENT_EXIT_WAIT_SECONDS = 5.0
logger = logging.getLogger(__name__)


async def terminate_bot_process(
    *,
    signal_parent: bool,
    reason: str,
) -> None:
    current_pid = os.getpid()
    parent_pid = os.getppid()
    target_pid = (
        parent_pid
        if signal_parent and parent_pid > 0
        else current_pid
    )
    logger.warning(
        "%s: current_pid=%s, target_pid=%s",
        reason,
        current_pid,
        target_pid,
    )
    os.kill(target_pid, signal.SIGTERM)
    if target_pid != current_pid:
        await asyncio.sleep(PARENT_EXIT_WAIT_SECONDS)
        logger.warning(
            "%s: parent did not stop current worker yet; "
            "sending SIGTERM to current_pid=%s",
            reason,
            current_pid,
        )
        os.kill(current_pid, signal.SIGTERM)
