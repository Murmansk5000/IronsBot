# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote
from uuid import uuid4

import httpx
from anyio import Path as AsyncPath

from ironsbot.services.operations.docker_models import (
    DockerImageInfo,
    DockerUpdateResult,
    WatchtowerUpdateOptions,
)

from .metadata import resolve_image_commit_summary

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


def split_docker_image(image: str) -> tuple[str, str]:
    last_segment = image.rsplit("/", maxsplit=1)[-1]
    if ":" not in last_segment:
        return image, "latest"
    repository, tag = image.rsplit(":", maxsplit=1)
    return repository, tag


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

    async def start_update(
        self,
        *,
        container_name: str,
        image: str,
        socket_path: str,
        watchtower: WatchtowerUpdateOptions,
        timeout_seconds: float,
    ) -> DockerUpdateResult:
        logger.warning(
            "admin requested docker self update: container=%s, watchtower=%s",
            container_name,
            watchtower.image,
        )
        if not await self.socket_exists(socket_path):
            logger.warning(
                "docker self update failed: socket not found: %s",
                socket_path,
            )
            return DockerUpdateResult(
                ok=False,
                missing_socket=True,
                message=f"Docker socket not found: {socket_path}",
            )

        transport = httpx.AsyncHTTPTransport(uds=socket_path)
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://docker",
                timeout=httpx.Timeout(timeout_seconds),
            ) as client:
                current_image_id = await inspect_container_image_id(
                    client,
                    container_name,
                )
                current_image_info = await inspect_image_info(client, current_image_id)
                target_image_info = await pull_docker_image(client, image)
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

                await ensure_watchtower_image(client, watchtower.image)
                updater_id = await create_watchtower_container(
                    client,
                    container_name=container_name,
                    socket_path=socket_path,
                    watchtower=watchtower,
                )
                response = await client.post(f"/containers/{updater_id}/start")
                _raise_for_docker_status(response)
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


async def pull_docker_image(
    client: httpx.AsyncClient,
    image: str,
) -> DockerImageInfo:
    repository, tag = split_docker_image(image)
    for attempt in range(1, IMAGE_PULL_RETRY_ATTEMPTS + 1):
        try:
            response = await client.post(
                "/images/create",
                params={"fromImage": repository, "tag": tag},
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
    return DockerImageInfo(
        image_id=image_id,
        created=created if isinstance(created, str) else "",
        labels=raw_labels,
    )

async def create_watchtower_container(
    client: httpx.AsyncClient,
    *,
    container_name: str,
    socket_path: str,
    watchtower: WatchtowerUpdateOptions,
) -> str:
    updater_name = f"ironsbot-watchtower-once-{uuid4().hex[:12]}"
    response = await client.post(
        "/containers/create",
        params={"name": updater_name},
        json={
            "Image": watchtower.image,
            "Cmd": ["--run-once", "--cleanup", container_name],
            "Env": [f"DOCKER_API_VERSION={watchtower.docker_api_version}"],
            "HostConfig": {
                "AutoRemove": True,
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
