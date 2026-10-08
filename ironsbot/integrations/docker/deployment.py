# SPDX-License-Identifier: MIT
"""Docker deployment supervision independent of the application process."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

from .cleanup import cleanup_images
from .daemon import inspect_image_info
from .http import raise_for_docker_status

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.services.operations.docker_models import DockerImageInfo

STARTUP_SECONDS = 120.0
STABLE_SECONDS = 60.0
STATE_FILE = "operations/docker_deployment.json"
HTTP_NOT_FOUND = 404
HTTP_NOT_MODIFIED = 304
BOOT_SUPERVISION_SECONDS = 300
logger = logging.getLogger(__name__)


class DeploymentError(RuntimeError):
    pass


async def inspect_container(client: httpx.AsyncClient, name: str) -> dict[str, Any]:
    response = await client.get(f"/containers/{quote(name, safe='')}/json")
    raise_for_docker_status(response)
    data = response.json()
    if not isinstance(data, dict) or not data.get("Id"):
        message = "Invalid container inspection"
        raise DeploymentError(message)
    return data


async def validate_container(
    client: httpx.AsyncClient,
    name: str,
    image: str,
    *,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict[str, Any]:
    deadline = now() + STARTUP_SECONDS
    original = await inspect_container(client, name)
    ident = original["Id"]
    started_at = original.get("State", {}).get("StartedAt")
    ready_at: float | None = None
    while True:
        data = await inspect_container(client, name)
        state = data.get("State", {})
        if (
            data["Id"] != ident
            or data.get("Image") != image
            or not state.get("Running")
            or state.get("OOMKilled")
            or data.get("RestartCount", 0) != original.get("RestartCount", 0)
            or state.get("StartedAt") != started_at
        ):
            message = "Container exited, restarted, or changed during verification"
            raise DeploymentError(message)
        if ready_at is None:
            response = await client.get(
                f"/containers/{ident}/logs",
                params={
                    "stdout": "true",
                    "stderr": "true",
                    "since": str(int(datetime.fromisoformat(started_at).timestamp())),
                    "tail": "all",
                },
            )
            raise_for_docker_status(response)
            if now() > deadline:
                message = "Application did not start within 120 seconds"
                raise DeploymentError(message)
            if b"Application startup complete." in response.content:
                ready_at = now()
            elif now() >= deadline:
                message = "Application did not start within 120 seconds"
                raise DeploymentError(message)
        if ready_at is not None and now() - ready_at >= STABLE_SECONDS:
            return data
        await sleep(2.0)


def write_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(record, stream)
    temporary.replace(path)


def recovery_record(path: Path, record: dict[str, Any]) -> None:
    """A full disk must never prevent restarting the previous container."""
    try:
        write_record(path, record)
    except OSError:
        logger.warning("Could not persist IronsBot recovery state")


async def docker_post(
    client: httpx.AsyncClient, path: str, **kwargs: Any
) -> httpx.Response:
    response = await client.post(path, **kwargs)
    if response.status_code != HTTP_NOT_MODIFIED:
        raise_for_docker_status(response)
    return response


async def remove_stopped(client: httpx.AsyncClient, ident: str) -> None:
    response = await client.delete(
        f"/containers/{quote(ident, safe='')}", params={"force": "false", "v": "false"}
    )
    if response.status_code != HTTP_NOT_FOUND:
        raise_for_docker_status(response)


async def restore_container(
    client: httpx.AsyncClient,
    *,
    old: dict[str, Any],
    new_id: str,
    name: str,
    renamed: bool,
) -> None:
    if new_id:
        await docker_post(client, f"/containers/{new_id}/stop", params={"t": 10})
        await remove_stopped(client, new_id)
    current = await inspect_container(client, old["Id"])
    if renamed or (current.get("Name") and current["Name"].lstrip("/") != name):
        await docker_post(
            client, f"/containers/{old['Id']}/rename", params={"name": name}
        )
    for network, endpoint in recreation_config(old, old["Image"])["NetworkingConfig"][
        "EndpointsConfig"
    ].items():
        if network not in current.get("NetworkSettings", {}).get("Networks", {}):
            await docker_post(
                client,
                f"/networks/{quote(network, safe='')}/connect",
                json={"Container": old["Id"], "EndpointConfig": endpoint},
            )
    await docker_post(client, f"/containers/{old['Id']}/start")


def recreation_config(old: dict[str, Any], image: str) -> dict[str, Any]:
    config = deepcopy(old["Config"])
    host = deepcopy(old["HostConfig"])
    bound = {bind.split(":", 2)[1] for bind in host.get("Binds") or [] if ":" in bind}
    bound.update(mount.get("Target") for mount in host.get("Mounts") or [])
    mounts = list(host.get("Mounts") or [])
    mounts.extend(
        {
            "Type": mount["Type"],
            "Source": mount.get("Name")
            if mount["Type"] == "volume"
            else mount["Source"],
            "Target": mount["Destination"],
            "ReadOnly": not mount.get("RW", False),
        }
        for mount in old.get("Mounts", [])
        if mount["Destination"] not in bound and mount["Type"] in {"bind", "volume"}
    )
    if mounts:
        host["Mounts"] = mounts
    config.update(Image=image, HostConfig=host)
    config["Labels"] = {
        key: value
        for key, value in (config.get("Labels") or {}).items()
        if not key.startswith("org.opencontainers.image.")
    }
    if config.get("Hostname") == old["Id"][:12]:
        config.pop("Hostname")
    config["NetworkingConfig"] = {
        "EndpointsConfig": {
            key: {
                field: value
                for field, value in endpoint.items()
                if field in {"Aliases", "IPAMConfig", "DriverOpts"} and value
            }
            for key, endpoint in old.get("NetworkSettings", {})
            .get("Networks", {})
            .items()
        }
    }
    return config


async def prepare_previous(
    client: httpx.AsyncClient, old: dict[str, Any], backup: str
) -> None:
    await docker_post(client, f"/containers/{old['Id']}/stop", params={"t": 30})
    await docker_post(
        client, f"/containers/{old['Id']}/rename", params={"name": backup}
    )
    for network, endpoint in old.get("NetworkSettings", {}).get("Networks", {}).items():
        if endpoint.get("IPAMConfig"):
            await docker_post(
                client,
                f"/networks/{quote(network, safe='')}/disconnect",
                json={"Container": old["Id"], "Force": False},
            )


async def owned_deployment_images(
    client: httpx.AsyncClient, old: dict[str, Any], image: str
) -> DockerImageInfo:
    target = await inspect_image_info(client, image)
    previous = await inspect_image_info(client, old["Image"])
    source = target.labels.get("org.opencontainers.image.source")
    if not source or source != previous.labels.get("org.opencontainers.image.source"):
        message = "Deployment image source differs from the existing application"
        raise DeploymentError(message)
    return target


async def deploy(  # noqa: PLR0913 - explicit transaction inputs and testable validator
    client: httpx.AsyncClient,
    *,
    name: str,
    image: str,
    record_path: Path,
    repository_image: str = "",
    validate: Callable[..., Awaitable[dict[str, Any]]] = validate_container,
) -> bool:
    old = await inspect_container(client, name)
    target = await owned_deployment_images(client, old, image)
    if old["Image"] == target.image_id:
        await validate(client, name, target.image_id)
        await cleanup_images(
            client, repository_image=repository_image or image, current_image=target
        )
        return True
    backup = f"{name}-rollback-{old['Id'][:12]}"
    record = {
        "phase": "preparing",
        "container_name": name,
        "source_id": old["Id"],
        "source_hostname": old["Config"].get("Hostname", ""),
        "target_image_id": target.image_id,
        "backup_name": backup,
        "created_at": time.time(),
        "old_container": old,
    }
    write_record(record_path, record)
    new_id = ""
    renamed = False
    try:
        await prepare_previous(client, old, backup)
        renamed = True
        config = recreation_config(old, target.image_id)
        record["target_hostname"] = config.get("Hostname", "")
        record["phase"] = "verifying"
        write_record(record_path, record)
        response = await docker_post(
            client, "/containers/create", params={"name": name}, json=config
        )
        new_id = str(response.json()["Id"])
        record["new_id"] = new_id
        write_record(record_path, record)
        await docker_post(client, f"/containers/{new_id}/start")
        await validate(client, name, target.image_id)
    except Exception:  # noqa: BLE001 - always restore before reporting failure
        logger.error("IronsBot deployment failed; restoring previous container")  # noqa: TRY400 - suppress potentially sensitive Docker response details
        record["phase"] = "rolling_back"
        recovery_record(record_path, record)
        try:
            await restore_container(
                client, old=old, new_id=new_id, name=name, renamed=renamed
            )
            await validate(client, name, old["Image"])
            record.update(phase="rolled_back", completed_at=time.time())
        except Exception:  # noqa: BLE001 - preserve recovery evidence on failure
            record.update(phase="rollback_failed", completed_at=time.time())
            recovery_record(record_path, record)
            message = "Deployment and rollback verification failed"
            raise DeploymentError(message) from None
        record.pop("old_container", None)
        recovery_record(record_path, record)
        return False
    record.update(phase="succeeded", completed_at=time.time())
    record.pop("old_container", None)
    # Success is committed before cleanup; cleanup failure must not roll it back.
    write_record(record_path, record)
    try:
        await remove_stopped(client, old["Id"])
        removed, retained = await cleanup_images(
            client, repository_image=repository_image or image, current_image=target
        )
        logger.info("IronsBot cleanup: removed=%d retained=%d", removed, retained)
    except Exception as exc:  # noqa: BLE001 - cleanup is best effort after success
        logger.warning(
            "Verified IronsBot deployment has pending cleanup backup=%s reason=%s",
            backup,
            type(exc).__name__,
        )
    return True


def boot_is_supervised(
    path: Path, *, instance_id: str, now: float | None = None
) -> bool:
    """Let supervised target/restored source boot without starting another update."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(record, dict):
        return False
    phase = record.get("phase")
    instance = record.get("new_id") if phase == "verifying" else record.get("source_id")
    hostname = (
        record.get("target_hostname")
        if phase == "verifying"
        else record.get("source_hostname")
    )
    if (
        not isinstance(instance, str)
        or not instance_id
        or not (instance.startswith(instance_id) or hostname == instance_id)
    ):
        return False
    timestamp = record.get("completed_at", record.get("created_at", 0))
    return (
        phase in {"verifying", "rolling_back", "rolled_back"}
        and isinstance(timestamp, int | float)
        and 0
        <= (now if now is not None else time.time()) - timestamp
        < BOOT_SUPERVISION_SECONDS
    )


async def run_cli() -> int:
    import fcntl

    parser = argparse.ArgumentParser()
    parser.add_argument("--container", default="ironsbot")
    parser.add_argument("--image", required=True)
    parser.add_argument("--repository", default="")
    parser.add_argument("--socket", default="/var/run/docker.sock")
    parser.add_argument("--state-dir", default="/state")
    args = parser.parse_args()
    lock = Path(args.state_dir) / "operations/docker_deployment.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    transport = httpx.AsyncHTTPTransport(uds=args.socket)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://docker", timeout=40
    ) as client:
        await asyncio.sleep(3)
        return (
            0
            if await deploy(
                client,
                name=args.container,
                image=args.image,
                repository_image=args.repository,
                record_path=Path(args.state_dir) / STATE_FILE,
            )
            else 1
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(run_cli()))
