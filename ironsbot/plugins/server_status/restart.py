# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Literal

from anyio import Path as AsyncPath

from .docker_update import (
    DockerUpdateResult,
    WatchtowerUpdateOptions,
    format_docker_update_reply,
    is_docker_update_started,
    resolve_docker_container_name,
    start_watchtower_update,
)

if TYPE_CHECKING:
    from .config import DockerUpdateConfig

RestartAction = Literal["none", "process", "docker"]

_docker_update_lock = asyncio.Lock()


class DockerSelfUpdateService:
    def __init__(self, config: DockerUpdateConfig) -> None:
        self._config = config

    def resolve_container_name(self) -> str:
        return resolve_docker_container_name(str(self._config.container_name))

    async def run(self) -> tuple[str, DockerUpdateResult]:
        container_name = self.resolve_container_name()
        async with _docker_update_lock:
            result = await start_watchtower_update(
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


class RestartService:
    def __init__(self, config: DockerUpdateConfig) -> None:
        self._config = config

    async def prepare_manual_restart(self) -> tuple[str, RestartAction]:
        if not bool(self._config.check_on_restart):
            return await self._prepare_restart_without_image_check()

        container_name, result = await DockerSelfUpdateService(self._config).run()
        reply = format_docker_update_reply(
            container_name=container_name,
            image=str(self._config.image),
            result=result,
        )
        if is_docker_update_started(result):
            message = reply
            action: RestartAction = "none"
        elif result.up_to_date:
            message = f"{reply}\n\n镜像已是最新，正在重启当前容器。"
            action = "docker"
        elif result.missing_socket:
            message = f"{reply}\n\n将跳过镜像检查并继续普通进程重启。"
            action = "process"
        else:
            action = await self._ordinary_restart_action()
            if action == "docker":
                message = f"{reply}\n\n镜像检查失败，仍将重启当前容器。"
            else:
                message = f"{reply}\n\n镜像检查失败，继续普通进程重启。"

        return message, action

    async def _prepare_restart_without_image_check(self) -> tuple[str, RestartAction]:
        action = await self._ordinary_restart_action()
        if action == "docker":
            message = (
                "正在重启机器人容器。\n"
                "当前配置未启用重启前镜像检查；将直接重启当前 Docker 容器。"
            )
        else:
            message = "正在重启机器人进程。"
        return message, action

    async def _ordinary_restart_action(self) -> RestartAction:
        socket_path = str(getattr(self._config, "docker_socket_path", "")).strip()
        if socket_path and await AsyncPath(socket_path).exists():
            return "docker"
        return "process"

