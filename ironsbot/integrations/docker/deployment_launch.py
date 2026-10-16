# SPDX-License-Identifier: MIT
"""Start an isolated deployment supervisor using an already pulled image."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import PurePosixPath
from urllib.parse import quote
from uuid import uuid4

import httpx

from .deployment import DeploymentError, inspect_container
from .http import raise_for_docker_status

HTTP_NOT_FOUND = 404


async def launch_supervisor(  # noqa: PLR0913 - explicit deployment handoff inputs
    client: httpx.AsyncClient,
    *,
    container_name: str,
    image: str,
    socket_path: str,
    repository_image: str = "",
    config_next: str = "",
    sqlite_path: str = "",
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
    binds = [f"{socket_path}:/var/run/docker.sock", f"{source}:/state"]
    config_args: list[str] = []
    if config_next:
        if PurePosixPath(config_next).name != config_next or config_next in {".", ".."}:
            message = "Candidate configuration must be a filename"
            raise DeploymentError(message)
        config_mount = next(
            (
                mount
                for mount in old.get("Mounts", [])
                if mount.get("Destination") == "/config"
            ),
            None,
        )
        config_path = next(
            (
                value.removeprefix("APP_CONFIG_PATH=")
                for value in old["Config"].get("Env", [])
                if value.startswith("APP_CONFIG_PATH=")
            ),
            "",
        )
        if (
            not config_mount
            or config_mount.get("Type") != "bind"
            or PurePosixPath(config_path).parent != PurePosixPath("/config")
        ):
            message = "Configuration handoff requires the existing /config bind mount"
            raise DeploymentError(message)
        binds.append(f"{config_mount['Source']}:/config:rw")
        config_args = [
            "--config-next",
            f"/config/{config_next}",
            "--config-target",
            config_path,
        ]
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
                *config_args,
                *(["--sqlite-path", sqlite_path] if sqlite_path else []),
            ],
            "Labels": {
                "io.ironsbot.role": "deployment-supervisor",
                "io.ironsbot.target": container_name,
            },
            "HostConfig": {
                "AutoRemove": True,
                "NetworkMode": "none",
                "Binds": binds,
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
    parser.add_argument("--config-next", default="")
    parser.add_argument("--sqlite-path", default="")
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
            config_next=args.config_next,
            sqlite_path=args.sqlite_path,
        )
        sys.stdout.write(f"IronsBot deployment supervisor started: {ident}\n")


if __name__ == "__main__":
    asyncio.run(main())
