# SPDX-License-Identifier: MIT
from __future__ import annotations

from nonebot.log import logger

from .config import get_docker_update_config
from .docker_update_formatting import format_docker_update_reply
from .restart import DockerSelfUpdateService

_startup_docker_update_state: dict[str, str | None] = {"notice": None}


def get_startup_docker_update_notice() -> str | None:
    return _startup_docker_update_state["notice"]


async def start_docker_update() -> None:
    _startup_docker_update_state["notice"] = None
    config = get_docker_update_config()
    if not config.check_on_startup:
        logger.info("startup docker image check disabled")
        return

    docker_update_service = DockerSelfUpdateService(config)
    container_name = docker_update_service.resolve_container_name()
    logger.warning(
        "startup docker image check enabled: container={}, image={}",
        container_name,
        config.image,
    )
    container_name, result = await docker_update_service.run()
    _startup_docker_update_state["notice"] = format_docker_update_reply(
        container_name=container_name,
        image=config.image,
        result=result,
    )


__all__ = [
    "get_startup_docker_update_notice",
    "start_docker_update",
]
