# SPDX-License-Identifier: MIT
"""Conservative, repository-scoped cleanup after a verified deployment."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import quote

from .http import raise_for_docker_status
from .registry import split_docker_image

if TYPE_CHECKING:
    import httpx

    from ironsbot.services.operations.docker_models import DockerImageInfo

logger = logging.getLogger(__name__)
SOURCE_LABEL = "org.opencontainers.image.source"
HTTP_NOT_FOUND = 404


async def delete_references(client: httpx.AsyncClient, refs: tuple[str, ...]) -> None:
    for ref in refs:
        deletion = await client.delete(
            f"/images/{quote(ref, safe='')}",
            params={"force": "false", "noprune": "true"},
        )
        if deletion.status_code != HTTP_NOT_FOUND:
            raise_for_docker_status(deletion)


def repository(tag: str) -> str:
    if tag in {"<none>:<none>", ""}:
        return ""
    value = split_docker_image(tag)[0]
    for prefix in ("docker.io/", "index.docker.io/", "registry-1.docker.io/"):
        value = value.removeprefix(prefix)
    return value


def owned_tags(
    tags: list[str],
    *,
    target: str,
    source_matches: bool,
) -> list[str]:
    result = []
    for tag in tags:
        repo = repository(tag)
        if repo == target or (
            source_matches
            and (
                (repo == "ironsbot" and tag.split(":")[-1].startswith("rollback-"))
                or repo == f"ghcr.io/{target.lower()}"
            )
        ):
            result.append(tag)
    return result


async def cleanup_images(
    client: httpx.AsyncClient,
    *,
    repository_image: str,
    current_image: DockerImageInfo,
) -> tuple[int, int]:
    """Never force removal, including when references change during cleanup."""
    response = await client.get("/containers/json", params={"all": "true"})
    raise_for_docker_status(response)
    containers = response.json()
    if not isinstance(containers, list):
        message = "Docker API returned invalid container list"
        raise TypeError(message)
    referenced = {item.get("ImageID") for item in containers if isinstance(item, dict)}
    response = await client.get("/images/json", params={"all": "true"})
    raise_for_docker_status(response)
    images = response.json()
    if not isinstance(images, list):
        message = "Docker API returned invalid image list"
        raise TypeError(message)
    target = repository(repository_image)
    source = current_image.labels.get(SOURCE_LABEL, "").strip()
    removed = retained = 0
    for item in images:
        if not isinstance(item, dict):
            continue
        ident = item.get("Id")
        if not isinstance(ident, str) or ident == current_image.image_id:
            continue
        tags = [tag for tag in item.get("RepoTags") or [] if isinstance(tag, str)]
        labels = item.get("Labels") or {}
        same_source = bool(
            source and isinstance(labels, dict) and labels.get(SOURCE_LABEL) == source
        )
        owned = owned_tags(tags, target=target, source_matches=same_source)
        dangling = not any(repository(tag) for tag in tags)
        if not owned and not (dangling and same_source):
            continue
        if ident in referenced or any(
            repository(tag) and tag not in owned for tag in tags
        ):
            retained += 1
            continue
        try:
            # Remove scoped tags first; multiple tags otherwise cause a 409.
            await delete_references(client, (*owned, ident))
            removed += 1
        except Exception as exc:  # noqa: BLE001 - cleanup cannot invalidate deployment
            retained += 1
            logger.warning(
                "IronsBot image cleanup retained image=%s reason=%s",
                ident[:19],
                type(exc).__name__,
            )
    return removed, retained
