# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Literal, Protocol

from .docker_formatting import format_docker_update_reply
from .docker_models import DockerUpdateResult, WatchtowerUpdateOptions

if TYPE_CHECKING:
    from ironsbot.config.models.operations import DockerUpdateConfig

RestartAction = Literal["none", "process", "docker"]
ProcessRestarter = Callable[[], Awaitable[None]]
RESTART_DELAY_SECONDS = 1.0
logger = logging.getLogger(__name__)


class DockerGateway(Protocol):
    async def socket_exists(self, socket_path: str) -> bool: ...

    async def start_update(
        self,
        *,
        container_name: str,
        image: str,
        socket_path: str,
        watchtower: WatchtowerUpdateOptions,
        timeout_seconds: float,
    ) -> DockerUpdateResult: ...

    async def restart_container(
        self,
        *,
        container_name: str,
        socket_path: str,
        timeout_seconds: float,
    ) -> None: ...


class DockerUpdateService:
    def __init__(
        self,
        config: DockerUpdateConfig,
        docker: DockerGateway,
        restart_process: ProcessRestarter,
    ) -> None:
        self._config = config
        self._docker = docker
        self._restart_process = restart_process
        self._lock = asyncio.Lock()

    async def run_update(self) -> tuple[str, DockerUpdateResult]:
        container_name = str(self._config.container_name)
        async with self._lock:
            result = await self._docker.start_update(
                container_name=container_name,
                image=str(self._config.image),
                socket_path=str(self._config.docker_socket_path),
                watchtower=WatchtowerUpdateOptions(
                    image=str(self._config.watchtower_image),
                    docker_api_version=str(
                        self._config.watchtower_docker_api_version
                    ),
                ),
                timeout_seconds=float(self._config.timeout_seconds),
            )
        return container_name, result

    async def startup_notice(self) -> str | None:
        if not self._config.check_on_startup:
            return None
        container_name, result = await self.run_update()
        return format_docker_update_reply(
            container_name=container_name,
            image=str(self._config.image),
            result=result,
        )

    async def prepare_manual_restart(self) -> tuple[str, RestartAction]:
        if not bool(self._config.check_on_restart):
            return await self._prepare_restart_without_image_check()

        container_name, result = await self.run_update()
        reply = format_docker_update_reply(
            container_name=container_name,
            image=str(self._config.image),
            result=result,
        )
        if result.ok and not result.up_to_date and result.updater_container_id:
            return reply, "none"
        if result.up_to_date:
            return f"{reply}\n\n镜像已是最新，正在重启当前容器。", "docker"
        if result.missing_socket:
            return f"{reply}\n\n将跳过镜像检查并继续普通进程重启。", "process"

        action = await self._ordinary_restart_action()
        suffix = (
            "镜像检查失败，仍将重启当前容器。"
            if action == "docker"
            else "镜像检查失败，继续普通进程重启。"
        )
        return f"{reply}\n\n{suffix}", action

    async def execute_restart(self, action: RestartAction) -> None:
        if action == "none":
            return
        await asyncio.sleep(RESTART_DELAY_SECONDS)
        if action == "process":
            await self._restart_process()
            return
        try:
            await self._docker.restart_container(
                container_name=str(self._config.container_name),
                socket_path=str(self._config.docker_socket_path),
                timeout_seconds=float(self._config.timeout_seconds),
            )
        except Exception:
            logger.exception(
                "docker container restart failed; falling back to process restart"
            )
            await self._restart_process()

    async def _prepare_restart_without_image_check(self) -> tuple[str, RestartAction]:
        action = await self._ordinary_restart_action()
        if action == "docker":
            return (
                "正在重启机器人容器。\n"
                "当前配置未启用重启前镜像检查；将直接重启当前 Docker 容器。",
                action,
            )
        return "正在重启机器人进程。", action

    async def _ordinary_restart_action(self) -> RestartAction:
        socket_path = str(self._config.docker_socket_path).strip()
        if socket_path and await self._docker.socket_exists(socket_path):
            return "docker"
        return "process"
