# SPDX-License-Identifier: MIT
"""Docker daemon API operations used by the update integration."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from urllib.parse import quote
from uuid import uuid4

from ironsbot.services.operations.docker_models import DockerImageInfo

from .http import raise_for_docker_status
from .registry import docker_registry_auth_headers, split_docker_image

if TYPE_CHECKING:
    import httpx

    from ironsbot.services.operations.docker_models import (
        DockerRegistryCredentials,
        WatchtowerUpdateOptions,
    )

IMAGE_PULL_RETRY_ATTEMPTS = 3
IMAGE_PULL_RETRY_BASE_DELAY_SECONDS = 2.0
HTTP_NOT_FOUND = 404
HTTP_CONFLICT = 409
TRANSIENT_DOCKER_PULL_ERRORS = (
    "eof",
    "timeout",
    "connection reset",
    "connection refused",
    "temporarily unavailable",
    "tls handshake timeout",
)
logger = logging.getLogger(__name__)


async def inspect_container_image_id(
    client: httpx.AsyncClient,
    container_name: str,
) -> str:
    response = await client.get(f"/containers/{quote(container_name, safe='')}/json")
    raise_for_docker_status(response)
    data = response.json()
    image_id = data.get("Image")
    if not isinstance(image_id, str) or not image_id:
        message = "Docker API did not return current container image id"
        raise RuntimeError(message)
    return image_id


async def create_archive_container(client: httpx.AsyncClient, image: str) -> str:
    response = await client.post(
        "/containers/create",
        json={"Image": image, "Cmd": ["true"]},
    )
    raise_for_docker_status(response)
    payload = response.json()
    container_id = payload.get("Id")
    if not isinstance(container_id, str) or not container_id:
        message = "Docker API did not return archive container id"
        raise RuntimeError(message)
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
    raise_for_docker_status(response)
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
        raise_for_docker_status(response)
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
    headers = docker_registry_auth_headers(registry_credentials)
    for attempt in range(1, IMAGE_PULL_RETRY_ATTEMPTS + 1):
        try:
            response = await client.post(
                "/images/create",
                params={"fromImage": repository, "tag": tag},
                headers=headers,
            )
            raise_for_docker_status(response)
            break
        except Exception as error:
            if attempt >= IMAGE_PULL_RETRY_ATTEMPTS or not is_transient_pull_error(
                error
            ):
                raise
            logger.warning(
                "docker image pull transient failure; retrying: image=%s, "
                "attempt=%s/%s, error=%s",
                image,
                attempt,
                IMAGE_PULL_RETRY_ATTEMPTS,
                error,
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


def _parse_image_info(data: object) -> DockerImageInfo:
    if not isinstance(data, dict):
        message = "Docker API returned invalid image metadata"
        raise TypeError(message)
    image_id = data.get("Id")
    if not isinstance(image_id, str) or not image_id:
        message = "Docker API did not return target image id"
        raise RuntimeError(message)
    created = data.get("Created")
    config = data.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    raw_labels = (
        {str(key): str(value) for key, value in labels.items() if value is not None}
        if isinstance(labels, dict)
        else {}
    )
    raw_repo_digests = data.get("RepoDigests")
    repo_digests = (
        tuple(value for value in raw_repo_digests if isinstance(value, str) and value)
        if isinstance(raw_repo_digests, list)
        else ()
    )
    return DockerImageInfo(
        image_id=image_id,
        created=created if isinstance(created, str) else "",
        labels=raw_labels,
        repo_digests=repo_digests,
    )


async def inspect_image_info(client: httpx.AsyncClient, image: str) -> DockerImageInfo:
    response = await client.get(f"/images/{quote(image, safe='')}/json")
    raise_for_docker_status(response)
    return _parse_image_info(response.json())


async def inspect_image_info_if_present(
    client: httpx.AsyncClient,
    image: str,
) -> DockerImageInfo | None:
    response = await client.get(f"/images/{quote(image, safe='')}/json")
    if response.status_code == HTTP_NOT_FOUND:
        return None
    raise_for_docker_status(response)
    return _parse_image_info(response.json())


async def remove_image_if_unused(
    client: httpx.AsyncClient,
    image_id: str,
) -> bool:
    """Remove one exact image without forcing containers that still reference it."""

    response = await client.delete(
        f"/images/{quote(image_id, safe='')}",
        params={"force": "false", "noprune": "false"},
    )
    if response.status_code == HTTP_NOT_FOUND:
        return True
    if response.status_code == HTTP_CONFLICT:
        return False
    raise_for_docker_status(response)
    return True


def _normalized_repository(repository: str) -> str:
    normalized = repository.removeprefix("docker.io/").removeprefix("index.docker.io/")
    return normalized.removeprefix("registry-1.docker.io/")


def _image_repository(tag: str) -> str:
    if tag == "<none>:<none>":
        return ""
    return split_docker_image(tag)[0]


async def remove_stale_repository_images(
    client: httpx.AsyncClient,
    *,
    repository_image: str,
    current_image: DockerImageInfo,
) -> tuple[int, int]:
    """Remove unused historical images belonging to the current repository."""

    response = await client.get("/images/json", params={"all": "true"})
    raise_for_docker_status(response)
    payload = response.json()
    if not isinstance(payload, list):
        message = "Docker API returned invalid image list"
        raise TypeError(message)

    target_repository = _normalized_repository(split_docker_image(repository_image)[0])
    current_source = current_image.labels.get(
        "org.opencontainers.image.source",
        "",
    )
    candidates: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        image_id = item.get("Id")
        if not isinstance(image_id, str) or not image_id:
            continue
        if image_id == current_image.image_id:
            continue
        raw_tags = item.get("RepoTags")
        repo_tags = (
            tuple(tag for tag in raw_tags if isinstance(tag, str) and tag)
            if isinstance(raw_tags, list)
            else ()
        )
        belongs_to_repository = any(
            _normalized_repository(_image_repository(tag)) == target_repository
            for tag in repo_tags
            if _image_repository(tag)
        )
        labels = item.get("Labels")
        image_source = (
            labels.get("org.opencontainers.image.source", "")
            if isinstance(labels, dict)
            else ""
        )
        is_dangling = not any(_image_repository(tag) for tag in repo_tags)
        belongs_to_dangling_source = bool(
            is_dangling and current_source and image_source == current_source
        )
        if belongs_to_repository or belongs_to_dangling_source:
            candidates.add(image_id)

    removed = 0
    retained = 0
    for image_id in sorted(candidates):
        if await remove_image_if_unused(client, image_id):
            removed += 1
        else:
            retained += 1
    return removed, retained


async def inspect_remote_image_digest(
    client: httpx.AsyncClient,
    image: str,
    *,
    registry_credentials: DockerRegistryCredentials | None = None,
) -> str:
    """Read a registry digest through Docker without pulling the image."""

    response = await client.get(
        f"/distribution/{quote(image, safe='')}/json",
        headers=docker_registry_auth_headers(registry_credentials),
    )
    raise_for_docker_status(response)
    payload = response.json()
    descriptor = payload.get("Descriptor") if isinstance(payload, dict) else None
    digest = descriptor.get("digest") if isinstance(descriptor, dict) else None
    if not isinstance(digest, str) or not digest:
        message = "Docker API did not return remote image manifest digest"
        raise RuntimeError(message)
    return digest


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
    raise_for_docker_status(response)
    data = response.json()
    container_id = data.get("Id")
    if not isinstance(container_id, str) or not container_id:
        message = "Docker API did not return updater container id"
        raise RuntimeError(message)
    return container_id


def is_transient_pull_error(error: Exception) -> bool:
    text = str(error).lower()
    return any(marker in text for marker in TRANSIENT_DOCKER_PULL_ERRORS)
