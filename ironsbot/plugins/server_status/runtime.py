# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

from nonebot import get_driver
from nonebot.log import logger

from .config import get_docker_update_config
from .docker_update import format_docker_update_reply
from .restart import DockerSelfUpdateService

_docker_update_runtime_state = {"registered": False}
_startup_docker_update_state: dict[str, str | None] = {"notice": None}


def get_startup_docker_update_notice() -> str | None:
    return _startup_docker_update_state["notice"]


async def _start_docker_update_runtime() -> None:
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


def _setup_docker_update_runtime(driver: Any) -> None:
    if _docker_update_runtime_state["registered"]:
        return

    @driver.on_startup
    async def _start_docker_update_on_startup() -> None:
        await _start_docker_update_runtime()

    _docker_update_runtime_state["registered"] = True


def setup_docker_update_runtime() -> None:
    _setup_docker_update_runtime(get_driver())


__all__ = [
    "get_startup_docker_update_notice",
    "setup_docker_update_runtime",
]
