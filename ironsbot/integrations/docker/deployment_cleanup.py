# SPDX-License-Identifier: MIT
"""Explicit legacy residue cleanup using the same verification and image policy."""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

from .cleanup import SOURCE_LABEL, cleanup_images
from .daemon import inspect_image_info
from .deployment import (
    DeploymentError,
    inspect_container,
    remove_stopped,
    validate_container,
)
from .http import raise_for_docker_status

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

HTTP_NOT_FOUND = 404
logger = logging.getLogger(__name__)


def mount_signature(container: dict[str, Any]) -> dict[str, tuple[str, str]]:
    return {
        mount["Destination"]: (mount.get("Type", ""), mount.get("Source", ""))
        for mount in container.get("Mounts", [])
        if isinstance(mount, dict)
    }


async def cleanup_residue(
    client: httpx.AsyncClient,
    *,
    name: str,
    repository_image: str,
    backups: tuple[str, ...] = (),
    validate: Callable[..., Awaitable[dict[str, Any]]] = validate_container,
) -> tuple[int, int, int]:
    current = await inspect_container(client, name)
    await validate(client, name, current["Image"])
    image = await inspect_image_info(client, current["Image"])
    source = image.labels.get(SOURCE_LABEL)
    removed_containers = 0
    for backup in backups:
        if not backup.startswith(f"{name}-before-"):
            message = (
                "Only explicitly named legacy IronsBot deployment backups are eligible"
            )
            raise DeploymentError(message)
        response = await client.get(f"/containers/{quote(backup, safe='')}/json")
        if response.status_code == HTTP_NOT_FOUND:
            continue
        raise_for_docker_status(response)
        old = response.json()
        old_image = await inspect_image_info(client, old["Image"])
        latest = await inspect_container(client, name)
        if (
            not source
            or old_image.labels.get(SOURCE_LABEL) != source
            or old.get("State", {}).get("Running")
            or old["Id"] == current["Id"]
            or mount_signature(old) != mount_signature(current)
            or latest["Id"] != current["Id"]
            or not latest.get("State", {}).get("Running")
        ):
            message = (
                "Legacy backup ownership or current deployment changed; cleanup stopped"
            )
            raise DeploymentError(message)
        await remove_stopped(client, old["Id"])
        removed_containers += 1
    removed, retained = await cleanup_images(
        client, repository_image=repository_image, current_image=image
    )
    return removed_containers, removed, retained


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", default="ironsbot")
    parser.add_argument("--image", default="murmansk5000/ironsbot:latest")
    parser.add_argument("--legacy-backup", action="append", default=[])
    parser.add_argument("--socket", default="/var/run/docker.sock")
    args = parser.parse_args()
    async with httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(uds=args.socket),
        base_url="http://docker",
        timeout=40,
    ) as client:
        containers, images, retained = await cleanup_residue(
            client,
            name=args.container,
            repository_image=args.image,
            backups=tuple(args.legacy_backup),
        )
        logger.info(
            "IronsBot cleanup: containers=%d images=%d retained=%d",
            containers,
            images,
            retained,
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
