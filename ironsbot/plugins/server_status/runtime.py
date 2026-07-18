# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.log import logger

from .docker_update_formatting import format_docker_update_reply
from .restart import DockerSelfUpdateService

if TYPE_CHECKING:
    from ironsbot.config.models.runtime import DockerUpdateConfig


async def start_docker_update(config: DockerUpdateConfig) -> str | None:
    if not config.check_on_startup:
        logger.info("startup docker image check disabled")
        return None

    docker_update_service = DockerSelfUpdateService(config)
    container_name = docker_update_service.resolve_container_name()
    logger.warning(
        "startup docker image check enabled: container={}, image={}",
        container_name,
        config.image,
    )
    container_name, result = await docker_update_service.run()
    return format_docker_update_reply(
        container_name=container_name,
        image=config.image,
        result=result,
    )
