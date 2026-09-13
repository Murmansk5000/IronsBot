# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Literal, Protocol

from .docker_formatting import (
    format_docker_image_check_reply,
    format_docker_update_reply,
)
from .docker_models import (
    DockerImageCheckResult,
    DockerRegistryCredentials,
    DockerUpdateRequest,
    DockerUpdateResult,
    WatchtowerUpdateOptions,
)

if TYPE_CHECKING:
    from ironsbot.config.models.operations import DockerUpdateConfig
    from ironsbot.services.operations.docker_preflight import (
        DockerStartupPreflightStore,
    )

RestartAction = Literal["none", "process", "docker"]
ProcessRestarter = Callable[[], Awaitable[None]]
RESTART_DELAY_SECONDS = 1.0
logger = logging.getLogger(__name__)


class DockerMaintenanceChoice(str, Enum):
    """Administrator-selected Docker maintenance action."""

    RESTART_ONLY = "restart_only"
    UPDATE_AND_RESTART = "update_and_restart"


@dataclass(frozen=True, slots=True)
class DockerMaintenanceOption:
    key: str
    label: str
    choice: DockerMaintenanceChoice


DOCKER_MAINTENANCE_OPTIONS = (
    DockerMaintenanceOption("1", "仅重启机器人", DockerMaintenanceChoice.RESTART_ONLY),
    DockerMaintenanceOption(
        "2",
        "检查并更新镜像后重启",
        DockerMaintenanceChoice.UPDATE_AND_RESTART,
    ),
)


def parse_docker_maintenance_choice(text: str) -> DockerMaintenanceChoice | None:
    normalized = text.strip()
    return next(
        (
            option.choice
            for option in DOCKER_MAINTENANCE_OPTIONS
            if option.key == normalized
        ),
        None,
    )


def docker_maintenance_menu_text() -> str:
    lines = ["选择机器人维护操作："]
    lines.extend(
        f"{option.key}. {option.label}" for option in DOCKER_MAINTENANCE_OPTIONS
    )
    lines.extend(("0.【退出】", "", "输入序号后会立即执行。"))
    return "\n".join(lines)


class DockerGateway(Protocol):
    async def socket_exists(self, socket_path: str) -> bool: ...

    async def start_update(
        self,
        request: DockerUpdateRequest,
    ) -> DockerUpdateResult: ...

    async def check_update(
        self,
        request: DockerUpdateRequest,
    ) -> DockerImageCheckResult: ...

    async def restart_container(
        self,
        *,
        container_name: str,
        socket_path: str,
        timeout_seconds: float,
    ) -> None: ...

    async def container_uses_image(
        self,
        *,
        container_name: str,
        expected_image_id: str,
        socket_path: str,
        timeout_seconds: float,
    ) -> bool: ...

    async def remove_container(
        self,
        *,
        container_id: str,
        socket_path: str,
        timeout_seconds: float,
    ) -> None: ...


class DockerUpdateService:
    def __init__(
        self,
        config: DockerUpdateConfig,
        docker: DockerGateway,
        restart_process: ProcessRestarter,
        *,
        handoff_store: DockerStartupPreflightStore | None = None,
        instance_id: str | None = None,
    ) -> None:
        self._config = config
        self._docker = docker
        self._restart_process = restart_process
        self._handoff_store = handoff_store
        self._instance_id = (
            instance_id if instance_id is not None else os.environ.get("HOSTNAME", "")
        )
        self._lock = asyncio.Lock()

    async def run_update(self) -> tuple[str, DockerUpdateResult]:
        container_name = str(self._config.container_name)
        async with self._lock:
            result = await self._docker.start_update(self._request(container_name))
        return container_name, result

    async def check_image_update(self) -> str:
        """Check the registry manifest without pulling or restarting anything."""

        container_name, result = await self._check_update()
        return format_docker_image_check_reply(
            container_name=container_name,
            image=str(self._config.image),
            result=result,
        )

    async def _check_update(self) -> tuple[str, DockerImageCheckResult]:
        container_name = str(self._config.container_name)
        async with self._lock:
            result = await self._docker.check_update(self._request(container_name))
        return container_name, result

    async def confirm_update_handoff(
        self,
        *,
        expected_image_id: str,
        updater_container_id: str,
    ) -> bool:
        """Confirm a recreated container really runs the pulled image."""

        socket_path = str(self._config.docker_socket_path)
        if not socket_path or not await self._docker.socket_exists(socket_path):
            return False
        async with self._lock:
            matches = await self._docker.container_uses_image(
                container_name=str(self._config.container_name),
                expected_image_id=expected_image_id,
                socket_path=socket_path,
                timeout_seconds=float(self._config.timeout_seconds),
            )
            if not matches:
                return False
            try:
                await self._docker.remove_container(
                    container_id=updater_container_id,
                    socket_path=socket_path,
                    timeout_seconds=float(self._config.timeout_seconds),
                )
            except (OSError, RuntimeError):
                logger.warning(
                    "could not remove completed Watchtower updater: %s",
                    updater_container_id,
                    exc_info=True,
                )
            return True

    async def abandon_update_handoff(
        self,
        *,
        updater_container_id: str,
    ) -> None:
        """Remove a failed one-shot updater before the current image boots."""

        if not updater_container_id:
            return
        socket_path = str(self._config.docker_socket_path)
        if not socket_path or not await self._docker.socket_exists(socket_path):
            return
        async with self._lock:
            await self._docker.remove_container(
                container_id=updater_container_id,
                socket_path=socket_path,
                timeout_seconds=float(self._config.timeout_seconds),
            )

    def _request(self, container_name: str) -> DockerUpdateRequest:
        return DockerUpdateRequest(
            container_name=container_name,
            image=str(self._config.image),
            socket_path=str(self._config.docker_socket_path),
            watchtower=WatchtowerUpdateOptions(
                image=str(self._config.watchtower_image),
                docker_api_version=str(self._config.watchtower_docker_api_version),
            ),
            timeout_seconds=float(self._config.timeout_seconds),
            registry_credentials=self._registry_credentials(),
        )

    def _registry_credentials(self) -> DockerRegistryCredentials | None:
        username = str(self._config.registry_username).strip()
        token = str(self._config.registry_token).strip()
        if not username and not token:
            return None
        return DockerRegistryCredentials(username=username, token=token)

    async def prepare_update_and_restart(self) -> tuple[str, RestartAction]:
        """Check for an image update, apply it when present, then restart."""

        container_name, result = await self.run_update()
        reply = format_docker_update_reply(
            container_name=container_name,
            image=str(self._config.image),
            result=result,
        )
        if result.ok and not result.up_to_date and result.updater_container_id:
            self._save_manual_handoff(container_name, result)
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

    async def prepare_restart_only(self) -> tuple[str, RestartAction]:
        """Prepare a restart without checking or updating the image."""

        action = await self._ordinary_restart_action()
        target = "机器人容器" if action == "docker" else "机器人进程"
        return (
            f"正在重启{target}。\n"
            "本次选择“仅重启”，不会检查或更新 Docker 镜像。",
            action,
        )

    async def prepare_maintenance(
        self,
        choice: DockerMaintenanceChoice,
    ) -> tuple[str, RestartAction]:
        """Prepare exactly the maintenance action selected by an administrator."""

        if choice is DockerMaintenanceChoice.RESTART_ONLY:
            return await self.prepare_restart_only()
        return await self.prepare_update_and_restart()

    def _save_manual_handoff(
        self,
        container_name: str,
        result: DockerUpdateResult,
    ) -> None:
        if self._handoff_store is None:
            return
        from ironsbot.services.operations.docker_preflight import (
            DockerStartupPreflightRecord,
        )

        try:
            self._handoff_store.save(
                DockerStartupPreflightRecord(
                    container_name=container_name,
                    image=str(self._config.image),
                    result=result,
                    source_instance_id=self._instance_id,
                )
            )
        except OSError:
            logger.warning(
                "could not persist manual Docker image handoff",
                exc_info=True,
            )

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

    async def _ordinary_restart_action(self) -> RestartAction:
        socket_path = str(self._config.docker_socket_path).strip()
        if socket_path and await self._docker.socket_exists(socket_path):
            return "docker"
        return "process"
