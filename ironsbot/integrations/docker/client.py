# SPDX-License-Identifier: MIT
"""Application use cases composed from Docker daemon and registry protocols."""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx
from anyio import Path as AsyncPath

from ironsbot.services.operations.docker_models import (
    DockerImageArchive,
    DockerImageArchiveRequest,
    DockerImageCheckResult,
    DockerImageInfo,
    DockerUpdateRequest,
    DockerUpdateResult,
)

from .daemon import (
    create_archive_container,
    create_watchtower_container,
    ensure_watchtower_image,
    inspect_container_image_id,
    inspect_image_info,
    inspect_remote_image_digest,
    pull_docker_image,
    read_container_archive,
    remove_container_quietly,
)
from .http import raise_for_docker_status
from .metadata import (
    github_repo_from_image_labels,
    resolve_github_branch_revision,
    resolve_image_commit_summary,
)
from .registry import inspect_remote_image_info, split_docker_image

RESTART_CONTAINER_STOP_TIMEOUT_SECONDS = 3
logger = logging.getLogger(__name__)


class DockerClient:
    """Run IronsBot's Docker maintenance use cases over the local daemon."""

    async def socket_exists(self, socket_path: str) -> bool:
        return await AsyncPath(socket_path).exists()

    async def restart_container(
        self,
        *,
        container_name: str,
        socket_path: str,
        timeout_seconds: float,
    ) -> None:
        if not await self.socket_exists(socket_path):
            message = f"Docker socket not found: {socket_path}"
            raise RuntimeError(message)

        logger.warning("admin requested docker container restart: %s", container_name)
        transport = httpx.AsyncHTTPTransport(uds=socket_path)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://docker",
            timeout=httpx.Timeout(timeout_seconds),
        ) as client:
            response = await client.post(
                f"/containers/{quote(container_name, safe='')}/restart",
                params={"t": RESTART_CONTAINER_STOP_TIMEOUT_SECONDS},
            )
            raise_for_docker_status(response)

    async def container_uses_image(
        self,
        *,
        container_name: str,
        expected_image_id: str,
        socket_path: str,
        timeout_seconds: float,
    ) -> bool:
        if not await self.socket_exists(socket_path):
            return False
        transport = httpx.AsyncHTTPTransport(uds=socket_path)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://docker",
            timeout=httpx.Timeout(timeout_seconds),
        ) as client:
            current_image_id = await inspect_container_image_id(client, container_name)
        return current_image_id == expected_image_id

    async def remove_container(
        self,
        *,
        container_id: str,
        socket_path: str,
        timeout_seconds: float,
    ) -> None:
        if not await self.socket_exists(socket_path):
            message = f"Docker socket not found: {socket_path}"
            raise RuntimeError(message)
        transport = httpx.AsyncHTTPTransport(uds=socket_path)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://docker",
            timeout=httpx.Timeout(timeout_seconds),
        ) as client:
            response = await client.delete(
                f"/containers/{quote(container_id, safe='')}",
                params={"force": "true"},
            )
            raise_for_docker_status(response)

    async def start_update(self, request: DockerUpdateRequest) -> DockerUpdateResult:
        logger.warning(
            "admin requested docker self update: container=%s, watchtower=%s",
            request.container_name,
            request.watchtower.image,
        )
        if not await self.socket_exists(request.socket_path):
            logger.warning(
                "docker self update failed: socket not found: %s",
                request.socket_path,
            )
            return DockerUpdateResult(
                ok=False,
                missing_socket=True,
                message=f"Docker socket not found: {request.socket_path}",
            )

        transport = httpx.AsyncHTTPTransport(uds=request.socket_path)
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://docker",
                timeout=httpx.Timeout(request.timeout_seconds),
            ) as client:
                current_image_id = await inspect_container_image_id(
                    client,
                    request.container_name,
                )
                current_image = await inspect_image_info(client, current_image_id)
                target_image = await pull_docker_image(
                    client,
                    request.image,
                    registry_credentials=request.registry_credentials,
                )
                current_commit = await resolve_image_commit_summary(
                    current_image,
                )
                target_commit = await resolve_image_commit_summary(
                    target_image,
                )
                if current_image.image_id == target_image.image_id:
                    return DockerUpdateResult(
                        ok=True,
                        up_to_date=True,
                        current_image_id=current_image.image_id,
                        current_image_created=current_image.created,
                        current_image_commit=current_commit,
                        target_image_id=target_image.image_id,
                        target_image_created=target_image.created,
                        target_image_commit=target_commit,
                    )

                await ensure_watchtower_image(client, request.watchtower.image)
                updater_id = await create_watchtower_container(
                    client,
                    container_name=request.container_name,
                    socket_path=request.socket_path,
                    watchtower=request.watchtower,
                    registry_credentials=request.registry_credentials,
                )
                response = await client.post(f"/containers/{updater_id}/start")
                raise_for_docker_status(response)
                logger.warning(
                    "Watchtower handoff started: container=%s updater=%s target=%s",
                    request.container_name,
                    updater_id,
                    target_image.image_id,
                )
        except Exception as error:
            logger.exception("docker self update failed")
            return DockerUpdateResult(ok=False, message=str(error))

        return DockerUpdateResult(
            ok=True,
            updater_container_id=updater_id,
            current_image_id=current_image.image_id,
            current_image_created=current_image.created,
            current_image_commit=current_commit,
            target_image_id=target_image.image_id,
            target_image_created=target_image.created,
            target_image_commit=target_commit,
        )

    async def check_update(
        self,
        request: DockerUpdateRequest,
    ) -> DockerImageCheckResult:
        """Compare the running image to the registry without pulling it."""

        logger.warning(
            "admin requested docker image check: container=%s, image=%s",
            request.container_name,
            request.image,
        )
        if not await self.socket_exists(request.socket_path):
            return DockerImageCheckResult(
                ok=False,
                missing_socket=True,
                message=f"Docker socket not found: {request.socket_path}",
            )

        transport = httpx.AsyncHTTPTransport(uds=request.socket_path)
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://docker",
                timeout=httpx.Timeout(request.timeout_seconds),
            ) as client:
                current_image_id = await inspect_container_image_id(
                    client,
                    request.container_name,
                )
                current_image = await inspect_image_info(client, current_image_id)
                remote_digest = await inspect_remote_image_digest(
                    client,
                    request.image,
                    registry_credentials=request.registry_credentials,
                )
                current_commit = await resolve_image_commit_summary(
                    current_image,
                )
            try:
                image_repository, _reference = split_docker_image(request.image)
                remote_image = await inspect_remote_image_info(
                    f"{image_repository}@{remote_digest}",
                    registry_credentials=request.registry_credentials,
                )
                remote_commit = await resolve_image_commit_summary(
                    remote_image,
                )
            except Exception as error:  # noqa: BLE001 - digest remains useful
                logger.warning(
                    "docker image metadata inspection failed: image=%s error=%s",
                    request.image,
                    error,
                )
                remote_image = DockerImageInfo(image_id="")
                remote_commit = ""
        except Exception as error:
            logger.exception("docker image check failed")
            return DockerImageCheckResult(ok=False, message=str(error))

        repository = github_repo_from_image_labels(
            remote_image.labels
        ) or github_repo_from_image_labels(current_image.labels)
        github_main_revision = ""
        github_main_error = "镜像未声明可识别的 GitHub 源码仓库，已跳过。"
        if repository is not None:
            try:
                github_main_revision = await resolve_github_branch_revision(repository)
                github_main_error = ""
            except Exception as error:  # noqa: BLE001 - optional diagnostics
                github_main_error = (
                    f"HTTP {error.response.status_code}"
                    if isinstance(error, httpx.HTTPStatusError)
                    else type(error).__name__
                )
                logger.warning(
                    "GitHub main check failed: repo=%s/%s reason=%s",
                    *repository,
                    github_main_error,
                )

        return DockerImageCheckResult(
            ok=True,
            up_to_date=remote_digest
            in {
                value.rsplit("@", maxsplit=1)[-1]
                for value in current_image.repo_digests
                if "@" in value
            },
            current_image_id=current_image.image_id,
            current_image_created=current_image.created,
            current_image_commit=current_commit,
            current_image_revision=current_image.labels.get(
                "org.opencontainers.image.revision",
                "",
            ).strip(),
            remote_digest=remote_digest,
            remote_image_id=remote_image.image_id,
            remote_image_created=remote_image.created,
            remote_image_commit=remote_commit,
            remote_image_revision=remote_image.labels.get(
                "org.opencontainers.image.revision",
                "",
            ).strip(),
            github_main_repository="/".join(repository) if repository else "",
            github_main_revision=github_main_revision,
            github_main_error=github_main_error,
        )

    async def fetch_image_archive(
        self,
        request: DockerImageArchiveRequest,
    ) -> DockerImageArchive:
        """Pull an image and read one directory without running its command."""

        if not await self.socket_exists(request.socket_path):
            message = f"Docker socket not found: {request.socket_path}"
            raise RuntimeError(message)

        transport = httpx.AsyncHTTPTransport(uds=request.socket_path)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://docker",
            timeout=httpx.Timeout(request.timeout_seconds),
        ) as client:
            image = await pull_docker_image(
                client,
                request.image,
                registry_credentials=request.registry_credentials,
            )
            container_id = await create_archive_container(client, request.image)
            try:
                content = await read_container_archive(
                    client,
                    container_id,
                    request.archive_path,
                )
            finally:
                await remove_container_quietly(client, container_id)
        return DockerImageArchive(image=image, content=content)
