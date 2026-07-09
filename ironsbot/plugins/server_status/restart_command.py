# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from nonebot import logger

from ironsbot.shared.messaging import send_event_reply

from .config import get_docker_update_config
from .docker_update import (
    resolve_docker_container_name,
    restart_docker_container,
)
from .process_restart import restart_bot_process
from .restart import RestartService

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent

BOT_RESTART_DELAY_SECONDS = 1.0


async def handle_restart_command(matcher: Any, event: MessageEvent) -> None:
    config = get_docker_update_config()
    restart_service = RestartService(config)
    message, restart_action = await restart_service.prepare_manual_restart()
    await send_event_reply(
        matcher,
        event,
        message,
        mention_sender=True,
    )
    if restart_action == "docker":
        await asyncio.sleep(BOT_RESTART_DELAY_SECONDS)
        try:
            await restart_docker_container(
                container_name=resolve_docker_container_name(
                    str(config.container_name)
                ),
                socket_path=str(config.docker_socket_path),
                timeout_seconds=float(config.timeout_seconds),
            )
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning(
                "docker container restart failed; falling back to process restart"
            )
            await restart_bot_process()
    elif restart_action == "process":
        await asyncio.sleep(BOT_RESTART_DELAY_SECONDS)
        await restart_bot_process()


__all__ = ["handle_restart_command"]
