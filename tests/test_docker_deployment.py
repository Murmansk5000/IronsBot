from __future__ import annotations

import json
from copy import deepcopy
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock
from urllib.parse import unquote

import httpx
import pytest

from ironsbot.integrations.docker import client as client_module
from ironsbot.integrations.docker.cleanup import SOURCE_LABEL, cleanup_images
from ironsbot.integrations.docker.client import DockerClient
from ironsbot.integrations.docker.deployment import (
    DeploymentError,
    boot_is_supervised,
    deploy,
    recreation_config,
    validate_container,
    write_record,
)
from ironsbot.integrations.docker.deployment_cleanup import cleanup_residue
from ironsbot.integrations.docker.deployment_launch import launch_supervisor
from ironsbot.services.operations.docker_models import (
    DockerImageInfo,
    DockerUpdateRequest,
    WatchtowerUpdateOptions,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch

SOURCE = "https://github.com/Murmansk5000/IronsBot"
REPO = "murmansk5000/ironsbot:latest"
READY_AT = 10
FAIL_AT = 20
VERIFIED_AT = 70


def container(ident: str = "old", image: str = "sha256:old") -> dict[str, Any]:
    return {
        "Id": ident,
        "Image": image,
        "RestartCount": 0,
        "State": {
            "Running": True,
            "OOMKilled": False,
            "StartedAt": "2026-10-08T00:00:00Z",
        },
        "Config": {"Image": REPO, "Env": ["SECRET=fictional"], "Hostname": ident},
        "HostConfig": {"Binds": ["/data:/app/data"]},
        "Mounts": [
            {"Type": "bind", "Source": "/data", "Destination": "/app/data", "RW": True}
        ],
    }


class Clock:
    value = 0.0

    def now(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.value += seconds


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [None, "restart", "exit", "oom", "image", "identity", "timeout"]
)
async def test_validation_requires_startup_and_sixty_stable_seconds(
    failure: str | None,
) -> None:
    clock = Clock()

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("logs"):
            assert request.url.params["since"].isdigit()
            ready = failure != "timeout" and clock.value >= READY_AT
            return httpx.Response(
                200, content=b"Application startup complete." if ready else b"waiting"
            )
        data = container()
        if clock.value >= FAIL_AT:
            if failure == "restart":
                data["RestartCount"] = 1
            elif failure == "exit":
                data["State"]["Running"] = False
            elif failure == "oom":
                data["State"]["OOMKilled"] = True
            elif failure == "image":
                data["Image"] = "sha256:other"
            elif failure == "identity":
                data["Id"] = "other"
        return httpx.Response(200, json=data)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://docker"
    ) as client:
        if failure:
            with pytest.raises(DeploymentError):
                await validate_container(
                    client, "ironsbot", "sha256:old", now=clock.now, sleep=clock.sleep
                )
        else:
            await validate_container(
                client, "ironsbot", "sha256:old", now=clock.now, sleep=clock.sleep
            )
            assert clock.value == VERIFIED_AT


@pytest.mark.asyncio
async def test_cleanup_is_scoped_reference_safe_and_multitag_idempotent() -> None:
    current = DockerImageInfo("sha256:current", labels={SOURCE_LABEL: SOURCE})
    images = [
        {"Id": "sha256:current", "RepoTags": [REPO]},
        {
            "Id": "sha256:old",
            "RepoTags": ["ironsbot:rollback-old", "ghcr.io/murmansk5000/ironsbot:old"],
            "Labels": {SOURCE_LABEL: SOURCE},
        },
        {"Id": "sha256:used", "RepoTags": ["murmansk5000/ironsbot:old"]},
        {"Id": "sha256:unknown", "RepoTags": ["ironsbot:rollback-unknown"]},
        {
            "Id": "sha256:private",
            "RepoTags": ["murmansk5000/ironsbot-private:latest"],
            "Labels": {SOURCE_LABEL: SOURCE},
        },
        {"Id": "sha256:watchtower", "RepoTags": ["containrrr/watchtower:latest"]},
        {"Id": "sha256:mixed", "RepoTags": ["murmansk5000/ironsbot:old", "other:keep"]},
        {"Id": "sha256:dangling", "RepoTags": [], "Labels": {SOURCE_LABEL: SOURCE}},
    ]
    deleted: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            assert request.url.params["force"] == "false"
            assert request.url.params["noprune"] == "true"
            ref = unquote(request.url.path.removeprefix("/images/"))
            deleted.append(ref)
            if ref.startswith("sha256:"):
                images[:] = [item for item in images if item["Id"] != ref]
            return httpx.Response(200)
        return httpx.Response(
            200,
            json=[{"ImageID": "sha256:used"}]
            if request.url.path == "/containers/json"
            else images,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://docker"
    ) as client:
        assert await cleanup_images(
            client, repository_image=REPO, current_image=current
        ) == (2, 2)
        assert await cleanup_images(
            client, repository_image=REPO, current_image=current
        ) == (0, 2)
    assert deleted == [
        "ironsbot:rollback-old",
        "ghcr.io/murmansk5000/ironsbot:old",
        "sha256:old",
        "sha256:dangling",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "target", "rollback", "cleanup"])
async def test_deployment_commit_rollback_and_cleanup(  # noqa: C901, PLR0915 - transaction fault matrix
    tmp_path: Path, failure: str | None
) -> None:
    calls: list[tuple[str, str]] = []
    validations: list[str] = []
    active = container()
    old = deepcopy(active)
    record_path = tmp_path / "deployment.json"

    def handle(request: httpx.Request) -> httpx.Response:  # noqa: PLR0911 - fake Docker endpoints
        nonlocal active
        path = request.url.path
        calls.append((request.method, path))
        if request.method == "GET":
            if path == "/containers/json":
                return httpx.Response(200, json=[{"ImageID": "sha256:new"}])
            if path == "/images/json":
                return httpx.Response(
                    200,
                    json=[
                        {"Id": "sha256:old", "RepoTags": ["murmansk5000/ironsbot:old"]}
                    ],
                )
            if path.startswith("/images/"):
                return httpx.Response(
                    200,
                    json={
                        "Id": "sha256:new",
                        "Config": {"Labels": {SOURCE_LABEL: SOURCE}},
                    },
                )
            return httpx.Response(200, json=active)
        if path == "/containers/create":
            body = json.loads(request.content)
            assert body["Env"] == ["SECRET=fictional"]
            assert body["HostConfig"] == old["HostConfig"]
            active = container("new", "sha256:new")
            return httpx.Response(201, json={"Id": "new"})
        if path == "/containers/old/start":
            active = old
        if request.method == "DELETE":
            assert request.url.params["force"] == "false"
            if path == "/containers/old" and failure == "cleanup":
                return httpx.Response(409, json={"message": "busy"})
        return httpx.Response(204)

    async def validate(
        _client: httpx.AsyncClient, _name: str, image: str
    ) -> dict[str, Any]:
        validations.append(image)
        assert ("DELETE", "/containers/old") not in calls
        if failure in {"target", "rollback"} and image == "sha256:new":
            raise DeploymentError
        if failure == "rollback" and image == "sha256:old":
            raise DeploymentError
        return active

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://docker"
    ) as client:
        if failure == "rollback":
            with pytest.raises(DeploymentError, match="rollback"):
                await deploy(
                    client,
                    name="ironsbot",
                    image=REPO,
                    record_path=record_path,
                    validate=validate,
                )
        else:
            assert await deploy(
                client,
                name="ironsbot",
                image=REPO,
                record_path=record_path,
                validate=validate,
            ) is (failure != "target")
    record = json.loads(record_path.read_text())
    if failure == "rollback":
        assert record["phase"] == "rollback_failed"
        assert "old_container" in record
    elif failure == "target":
        assert record["phase"] == "rolled_back"
        assert validations == ["sha256:new", "sha256:old"]
        assert ("DELETE", "/containers/old") not in calls
        assert not any(
            path.startswith("/images/") for method, path in calls if method == "DELETE"
        )
    else:
        assert record["phase"] == "succeeded"
        assert ("DELETE", "/containers/old") in calls
        assert validations == ["sha256:new"]
    if failure != "rollback":
        assert "fictional" not in record_path.read_text()


@pytest.mark.asyncio
async def test_supervisor_runs_outside_app_and_does_not_receive_credentials() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=container())
        if request.url.path == "/containers/create":
            body = json.loads(request.content)
            assert "Env" not in body
            assert body["HostConfig"] == {
                "AutoRemove": True,
                "NetworkMode": "none",
                "Binds": ["/var/run/docker.sock:/var/run/docker.sock", "/data:/state"],
            }
            assert "ironsbot.integrations.docker.deployment" in body["Entrypoint"]
            assert body["Cmd"][-1] == REPO
            return httpx.Response(201, json={"Id": "helper"})
        return httpx.Response(204)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://docker"
    ) as client:
        assert (
            await launch_supervisor(
                client,
                container_name="ironsbot",
                image="sha256:new",
                repository_image=REPO,
                socket_path="/var/run/docker.sock",
            )
            == "helper"
        )


@pytest.mark.parametrize(
    "phase,instance,expected",
    [
        ("verifying", "new", True),
        ("rolling_back", "old", True),
        ("rolled_back", "old", True),
        ("succeeded", "new", False),
        ("verifying", "other", False),
    ],
)
def test_supervised_boot_does_not_retrigger_update(
    tmp_path: Path, phase: str, instance: str, *, expected: bool
) -> None:
    path = tmp_path / "state.json"
    write_record(
        path, {"phase": phase, "new_id": "new", "source_id": "old", "created_at": 100}
    )
    assert boot_is_supervised(path, instance_id=instance, now=101) is expected
    assert not boot_is_supervised(path, instance_id=instance, now=501)


def test_recreation_preserves_anonymous_volume_and_does_not_reuse_endpoint_id() -> None:
    old = container()
    old["Mounts"].append(
        {
            "Type": "volume",
            "Name": "original-volume",
            "Source": "/docker/volumes/original-volume",
            "Destination": "/extra",
            "RW": True,
        }
    )
    old["NetworkSettings"] = {
        "Networks": {
            "custom": {
                "EndpointID": "stale",
                "IPAMConfig": {"IPv4Address": "172.19.0.8"},
                "Aliases": ["alias"],
            }
        }
    }
    config = recreation_config(old, "sha256:new")
    assert config["HostConfig"]["Mounts"] == [
        {
            "Type": "volume",
            "Source": "original-volume",
            "Target": "/extra",
            "ReadOnly": False,
        }
    ]
    assert config["NetworkingConfig"] == {
        "EndpointsConfig": {
            "custom": {
                "IPAMConfig": {"IPv4Address": "172.19.0.8"},
                "Aliases": ["alias"],
            }
        }
    }
    assert old["HostConfig"] == {"Binds": ["/data:/app/data"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "condition", ["valid", "running", "mount", "source", "missing", "changed"]
)
async def test_legacy_cleanup_requires_verified_live_container_and_trusted_backup(
    condition: str,
) -> None:
    deleted: list[str] = []
    verified = False
    current = container("live", "sha256:current")
    old = container("backup", "sha256:old")
    old["State"]["Running"] = condition == "running"
    if condition == "mount":
        old["Mounts"][0]["Source"] = "/another-app"

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            assert verified
            deleted.append(request.url.path)
            assert request.url.params["force"] == "false"
            assert request.url.params["v"] == "false"
            return httpx.Response(204)
        path = request.url.path
        if path in {"/containers/json", "/images/json"}:
            return httpx.Response(200, json=[])
        if path.startswith("/images/"):
            source = "different" if condition == "source" and "old" in path else SOURCE
            return httpx.Response(
                200,
                json={
                    "Id": "sha256:current",
                    "Config": {"Labels": {SOURCE_LABEL: source}},
                },
            )
        if "before-" in path:
            return httpx.Response(404 if condition == "missing" else 200, json=old)
        data = deepcopy(current)
        if verified and condition == "changed":
            data["Id"] = "replacement"
        return httpx.Response(200, json=data)

    async def validate(
        _client: httpx.AsyncClient, _name: str, _image: str
    ) -> dict[str, Any]:
        nonlocal verified
        verified = True
        return current

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://docker"
    ) as client:
        if condition in {"valid", "missing"}:
            assert await cleanup_residue(
                client,
                name="ironsbot",
                repository_image=REPO,
                backups=("ironsbot-before-master-20261008",),
                validate=validate,
            ) == (int(condition == "valid"), 0, 0)
        else:
            with pytest.raises(DeploymentError):
                await cleanup_residue(
                    client,
                    name="ironsbot",
                    repository_image=REPO,
                    backups=("ironsbot-before-master-20261008",),
                    validate=validate,
                )
    assert deleted == (["/containers/backup"] if condition == "valid" else [])


@pytest.mark.asyncio
async def test_update_client_starts_supervisor_exactly_once(
    monkeypatch: MonkeyPatch,
) -> None:
    starts: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/containers/json":
            return httpx.Response(200, json=[])
        if request.method == "GET":
            return httpx.Response(200, json=container())
        if request.url.path == "/containers/create":
            return httpx.Response(201, json={"Id": "helper"})
        if request.url.path == "/containers/helper/start":
            starts.append(request.url.path)
            return httpx.Response(204 if len(starts) == 1 else 304)
        pytest.fail(f"unexpected endpoint: {request.method} {request.url.path}")

    monkeypatch.setattr(
        httpx, "AsyncHTTPTransport", lambda **_kwargs: httpx.MockTransport(handle)
    )
    monkeypatch.setattr(DockerClient, "socket_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(
        client_module,
        "inspect_image_info",
        AsyncMock(return_value=DockerImageInfo("sha256:old")),
    )
    monkeypatch.setattr(
        client_module,
        "pull_docker_image",
        AsyncMock(return_value=DockerImageInfo("sha256:new")),
    )
    monkeypatch.setattr(
        client_module, "resolve_image_commit_summary", AsyncMock(return_value="commit")
    )
    result = await DockerClient().start_update(
        DockerUpdateRequest(
            container_name="ironsbot",
            image=REPO,
            socket_path="/var/run/docker.sock",
            timeout_seconds=40,
            watchtower=WatchtowerUpdateOptions("containrrr/watchtower:latest", "1.40"),
        )
    )
    assert result.ok and result.updater_container_id == "helper"
    assert starts == ["/containers/helper/start"]


def test_recovery_record_failure_is_nonfatal(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from ironsbot.integrations.docker import deployment

    def full_disk(*_args: object) -> None:
        raise OSError

    monkeypatch.setattr(deployment, "write_record", full_disk)
    deployment.recovery_record(tmp_path / "state.json", {"phase": "rolling_back"})
