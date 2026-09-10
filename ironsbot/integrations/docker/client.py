# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote
from uuid import uuid4

import httpx
from anyio import Path as AsyncPath

from ironsbot.services.operations.docker_models import (
    DockerImageArchive,
    DockerImageArchiveRequest,
    DockerImageCheckResult,
    DockerImageInfo,
    DockerRegistryCredentials,
    DockerUpdateRequest,
    DockerUpdateResult,
    WatchtowerUpdateOptions,
)

from .metadata import (
    github_repo_from_image_labels,
    resolve_github_branch_revision,
    resolve_image_commit_summary,
)
from .registry import (
    inspect_registry_image_info,  # noqa: F401 - compatibility export
    inspect_remote_image_digest,
    inspect_remote_image_info,
    split_docker_image,
)
from .registry import (
    registry_auth_headers as _registry_auth_headers,
)

RESTART_CONTAINER_STOP_TIMEOUT_SECONDS = 3
IMAGE_PULL_RETRY_ATTEMPTS = 3
IMAGE_PULL_RETRY_BASE_DELAY_SECONDS = 2.0
TRANSIENT_DOCKER_PULL_ERRORS = (
    "eof",
    "timeout",
    "connection reset",
    "connection refused",
    "temporarily unavailable",
    "tls handshake timeout",
)
logger = logging.getLogger(__name__)


def _docker_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip()
    if isinstance(payload, dict):
        for key in ("message", "error", "errorDetail"):
            detail = payload.get(key)
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
            if isinstance(detail, dict):
                message = detail.get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()
    return response.text.strip()


def _raise_for_docker_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = _docker_error_detail(response)
        if not detail:
            raise
        msg = f"Docker API returned HTTP {response.status_code}: {detail}"
        raise RuntimeError(msg) from exc


def _is_transient_docker_pull_error(error: Exception) -> bool:
    text = str(error).lower()
    return any(marker in text for marker in TRANSIENT_DOCKER_PULL_ERRORS)


class DockerClient:
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
            msg = f"Docker socket not found: {socket_path}"
            raise RuntimeError(msg)

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
            _raise_for_docker_status(response)

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
            current_image_id = await inspect_container_image_id(
                client,
                container_name,
            )
        return current_image_id == expected_image_id

    async def remove_container(
        self,
        *,
        container_id: str,
        socket_path: str,
        timeout_seconds: float,
    ) -> None:
        if not await self.socket_exists(socket_path):
            msg = f"Docker socket not found: {socket_path}"
            raise RuntimeError(msg)
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
            _raise_for_docker_status(response)

    async def start_update(
        self,
        request: DockerUpdateRequest,
    ) -> DockerUpdateResult:
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
                current_image_info = await inspect_image_info(client, current_image_id)
                target_image_info = await pull_docker_image(
                    client,
                    request.image,
                    registry_credentials=request.registry_credentials,
                )
                current_commit = await resolve_image_commit_summary(
                    current_image_info,
                    fallback_repo=("Murmansk5000", "IronsBot"),
                )
                target_commit = await resolve_image_commit_summary(
                    target_image_info,
                    fallback_repo=("Murmansk5000", "IronsBot"),
                )
                if current_image_info.image_id == target_image_info.image_id:
                    return DockerUpdateResult(
                        ok=True,
                        up_to_date=True,
                        current_image_id=current_image_info.image_id,
                        current_image_created=current_image_info.created,
                        current_image_commit=current_commit,
                        target_image_id=target_image_info.image_id,
                        target_image_created=target_image_info.created,
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
                _raise_for_docker_status(response)
                logger.warning(
                    "Watchtower handoff started: container=%s updater=%s target=%s",
                    request.container_name,
                    updater_id,
                    target_image_info.image_id,
                )
        except Exception as e:
            logger.exception("docker self update failed")
            return DockerUpdateResult(ok=False, message=str(e))

        return DockerUpdateResult(
            ok=True,
            updater_container_id=updater_id,
            current_image_id=current_image_info.image_id,
            current_image_created=current_image_info.created,
            current_image_commit=current_commit,
            target_image_id=target_image_info.image_id,
            target_image_created=target_image_info.created,
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
                    fallback_repo=("Murmansk5000", "IronsBot"),
                )
            try:
                remote_image = await inspect_remote_image_info(
                    request.image,
                    registry_credentials=request.registry_credentials,
                )
                remote_commit = await resolve_image_commit_summary(
                    remote_image,
                    fallback_repo=("Murmansk5000", "IronsBot"),
                )
            except Exception as error:  # noqa: BLE001 - digest remains useful
                logger.warning(
                    "docker image metadata inspection failed: image=%s error=%s",
                    request.image,
                    error,
                )
                remote_image = DockerImageInfo(image_id="")
                remote_commit = ""
            repository = (
                github_repo_from_image_labels(remote_image.labels)
                or github_repo_from_image_labels(current_image.labels)
                or ("Murmansk5000", "IronsBot")
            )
            try:
                github_main_revision = await resolve_github_branch_revision(repository)
                github_main_error = ""
            except Exception as error:  # noqa: BLE001 - optional diagnostics
                logger.warning(
                    "GitHub main revision check failed: "
                    "repo=%s/%s error_type=%s error=%s",
                    repository[0],
                    repository[1],
                    type(error).__name__,
                    error,
                )
                github_main_revision = ""
                github_main_error = f"{type(error).__name__}: {error}"
        except Exception as e:
            logger.exception("docker image check failed")
            return DockerImageCheckResult(ok=False, message=str(e))

        return DockerImageCheckResult(
            ok=True,
            up_to_date=remote_digest in {
                value.rsplit("@", maxsplit=1)[-1]
                for value in current_image.repo_digests
                if "@" in value
            },
            current_image_id=current_image.image_id,
            current_image_created=current_image.created,
            current_image_commit=current_commit,
            current_image_revision=current_image.labels.get(
                "org.opencontainers.image.revision", ""
            ).strip(),
            remote_digest=remote_digest,
            remote_image_id=remote_image.image_id,
            remote_image_created=remote_image.created,
            remote_image_commit=remote_commit,
            remote_image_revision=remote_image.labels.get(
                "org.opencontainers.image.revision", ""
            ).strip(),
            github_main_revision=github_main_revision,
            github_main_error=github_main_error,
        )

    async def fetch_image_archive(
        self,
        request: DockerImageArchiveRequest,
    ) -> DockerImageArchive:
        """Pull an image and read one directory without running its command."""

        if not await self.socket_exists(request.socket_path):
            msg = f"Docker socket not found: {request.socket_path}"
            raise RuntimeError(msg)

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

async def inspect_container_image_id(
    client: httpx.AsyncClient,
    container_name: str,
) -> str:
    response = await client.get(f"/containers/{quote(container_name, safe='')}/json")
    _raise_for_docker_status(response)
    data = response.json()
    image_id = data.get("Image")
    if not isinstance(image_id, str) or not image_id:
        msg = "Docker API did not return current container image id"
        raise RuntimeError(msg)
    return image_id


async def create_archive_container(client: httpx.AsyncClient, image: str) -> str:
    response = await client.post(
        "/containers/create",
        json={"Image": image, "Cmd": ["true"]},
    )
    _raise_for_docker_status(response)
    payload = response.json()
    container_id = payload.get("Id")
    if not isinstance(container_id, str) or not container_id:
        msg = "Docker API did not return archive container id"
        raise RuntimeError(msg)
    return container_id


async def read_container_archive(
    client: httpx.AsyncClient,
    container_id: str,
    archive_path: str,
) -> bytes:
    response = await client.get(
        f"/containers/{quote(container_id, safe='')}/archive",
        params={"path": archive_path},
    )
    _raise_for_docker_status(response)
    return response.content


async def remove_container_quietly(
    client: httpx.AsyncClient,
    container_id: str,
) -> None:
    try:
        response = await client.delete(
            f"/containers/{quote(container_id, safe='')}",
            params={"force": "true"},
        )
        _raise_for_docker_status(response)
    except Exception:  # noqa: BLE001 - never hide the original archive failure
        logger.warning(
            "could not remove temporary Docker archive container: %s",
            container_id,
            exc_info=True,
        )


async def pull_docker_image(
    client: httpx.AsyncClient,
    image: str,
    *,
    registry_credentials: DockerRegistryCredentials | None = None,
) -> DockerImageInfo:
    repository, tag = split_docker_image(image)
    headers = _registry_auth_headers(registry_credentials)
    for attempt in range(1, IMAGE_PULL_RETRY_ATTEMPTS + 1):
        try:
            response = await client.post(
                "/images/create",
                params={"fromImage": repository, "tag": tag},
                headers=headers,
            )
            _raise_for_docker_status(response)
            break
        except Exception as e:
            if (
                attempt >= IMAGE_PULL_RETRY_ATTEMPTS
                or not _is_transient_docker_pull_error(e)
            ):
                raise
            logger.warning(
                "docker image pull transient failure; retrying: image=%s, "
                "attempt=%s/%s, error=%s",
                image,
                attempt,
                IMAGE_PULL_RETRY_ATTEMPTS,
                e,
            )
            await asyncio.sleep(IMAGE_PULL_RETRY_BASE_DELAY_SECONDS * attempt)
    return await inspect_image_info(client, image)


async def ensure_watchtower_image(
    client: httpx.AsyncClient,
    image: str,
) -> DockerImageInfo:
    try:
        return await pull_docker_image(client, image)
    except Exception as pull_error:  # noqa: BLE001
        try:
            cached = await inspect_image_info(client, image)
        except Exception as cache_error:
            raise pull_error from cache_error
        logger.warning(
            "watchtower image pull failed; using cached local image: image=%s, "
            "image_id=%s, error=%s",
            image,
            cached.image_id[:19],
            pull_error,
        )
        return cached


async def inspect_image_info(client: httpx.AsyncClient, image: str) -> DockerImageInfo:
    response = await client.get(f"/images/{quote(image, safe='')}/json")
    _raise_for_docker_status(response)
    data = response.json()
    image_id = data.get("Id")
    if not isinstance(image_id, str) or not image_id:
        msg = "Docker API did not return target image id"
        raise RuntimeError(msg)
    created = data.get("Created")
    raw_labels = {}
    config = data.get("Config")
    if isinstance(config, dict):
        labels = config.get("Labels")
        if isinstance(labels, dict):
            raw_labels = {
                str(key): str(value)
                for key, value in labels.items()
                if value is not None
            }
    raw_repo_digests = data.get("RepoDigests")
    repo_digests = (
        tuple(
            value
            for value in raw_repo_digests
            if isinstance(value, str) and value
        )
        if isinstance(raw_repo_digests, list)
        else ()
    )
    return DockerImageInfo(
        image_id=image_id,
        created=created if isinstance(created, str) else "",
        labels=raw_labels,
        repo_digests=repo_digests,
    )


async def create_watchtower_container(
    client: httpx.AsyncClient,
    *,
    container_name: str,
    socket_path: str,
    watchtower: WatchtowerUpdateOptions,
    registry_credentials: DockerRegistryCredentials | None = None,
) -> str:
    updater_name = f"ironsbot-watchtower-once-{uuid4().hex[:12]}"
    environment = [f"DOCKER_API_VERSION={watchtower.docker_api_version}"]
    if registry_credentials is not None:
        environment.extend(
            [
                f"REPO_USER={registry_credentials.username}",
                f"REPO_PASS={registry_credentials.token}",
            ]
        )
    response = await client.post(
        "/containers/create",
        params={"name": updater_name},
        json={
            "Image": watchtower.image,
            "Cmd": ["--run-once", "--cleanup", container_name],
            "Env": environment,
            "HostConfig": {
                "AutoRemove": False,
                "Binds": [f"{socket_path}:/var/run/docker.sock"],
            },
        },
    )
    _raise_for_docker_status(response)
    data = response.json()
    container_id = data.get("Id")
    if not isinstance(container_id, str) or not container_id:
        msg = "Docker API did not return updater container id"
        raise RuntimeError(msg)
    return container_id
