# SPDX-License-Identifier: MIT
"""Start an isolated deployment supervisor using an already pulled image."""

from __future__ import annotations

import argparse
import asyncio
import sys
from urllib.parse import quote
from uuid import uuid4

import httpx

from .deployment import DeploymentError, inspect_container
from .http import raise_for_docker_status

HTTP_NOT_FOUND = 404


async def launch_supervisor(
    client: httpx.AsyncClient,
    *,
    container_name: str,
    image: str,
    socket_path: str,
    repository_image: str = "",
) -> str:
    old = await inspect_container(client, container_name)
    data_mount = next(
        (
            mount
            for mount in old.get("Mounts", [])
            if mount.get("Destination") == "/app/data"
        ),
        None,
    )
    if not data_mount or data_mount.get("Type") not in {"bind", "volume"}:
        message = "Deployment needs the existing persistent /app/data mount"
        raise DeploymentError(message)
    source = (
        data_mount.get("Name")
        if data_mount["Type"] == "volume"
        else data_mount.get("Source")
    )
    if not source or not data_mount.get("RW"):
        message = "Deployment state mount must be writable"
        raise DeploymentError(message)
    response = await client.post(
        "/containers/create",
        params={"name": f"ironsbot-deploy-once-{uuid4().hex[:12]}"},
        json={
            "Image": image,
            "Entrypoint": ["python", "-m", "ironsbot.integrations.docker.deployment"],
            "Cmd": [
                "--container",
                container_name,
                "--image",
                image,
                "--repository",
                repository_image or image,
            ],
            "Labels": {
                "io.ironsbot.role": "deployment-supervisor",
                "io.ironsbot.target": container_name,
            },
            "HostConfig": {
                "AutoRemove": True,
                "NetworkMode": "none",
                "Binds": [f"{socket_path}:/var/run/docker.sock", f"{source}:/state"],
            },
        },
    )
    raise_for_docker_status(response)
    ident = response.json().get("Id")
    if not isinstance(ident, str) or not ident:
        message = "Docker API did not return supervisor ID"
        raise DeploymentError(message)
    try:
        response = await client.post(f"/containers/{quote(ident, safe='')}/start")
        raise_for_docker_status(response)
    except Exception:
        response = await client.delete(
            f"/containers/{quote(ident, safe='')}",
            params={"force": "false", "v": "false"},
        )
        if response.status_code != HTTP_NOT_FOUND:
            raise_for_docker_status(response)
        raise
    return ident


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deploy an already pulled IronsBot image with verified rollback"
    )
    parser.add_argument("--container", default="ironsbot")
    parser.add_argument("--image", required=True)
    parser.add_argument("--socket", default="/var/run/docker.sock")
    args = parser.parse_args()
    async with httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(uds=args.socket),
        base_url="http://docker",
        timeout=40,
    ) as client:
        ident = await launch_supervisor(
            client,
            container_name=args.container,
            image=args.image,
            socket_path=args.socket,
        )
        sys.stdout.write(f"IronsBot deployment supervisor started: {ident}\n")


if __name__ == "__main__":
    asyncio.run(main())
