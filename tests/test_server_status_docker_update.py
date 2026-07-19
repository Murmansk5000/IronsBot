import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

import httpx
import nonebot
import pytest

if TYPE_CHECKING:
    from nonebot.internal.driver import Driver

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.app.lifecycle import ApplicationLifecycle, TaskOwner
from ironsbot.config.models.operations import DockerUpdateConfig
from ironsbot.integrations.docker.client import (
    DockerClient,
    create_watchtower_container,
    ensure_watchtower_image,
    pull_docker_image,
    split_docker_image,
)
from ironsbot.services.operations.docker_formatting import (
    format_docker_image_created,
    format_docker_update_reply,
)
from ironsbot.services.operations.docker_models import (
    DockerUpdateResult,
    WatchtowerUpdateOptions,
)
from ironsbot.services.operations.docker_update import DockerUpdateService
from tests.helpers.plugin_registry import build_test_plugin_registry


async def noop_restart_process() -> None:
    return None


def build_docker_service(config: DockerUpdateConfig) -> DockerUpdateService:
    return DockerUpdateService(config, DockerClient(), noop_restart_process)


def test_split_docker_image_with_tag() -> None:
    assert split_docker_image("containrrr/watchtower:latest") == (
        "containrrr/watchtower",
        "latest",
    )


def test_split_docker_image_defaults_latest() -> None:
    assert split_docker_image("containrrr/watchtower") == (
        "containrrr/watchtower",
        "latest",
    )


def test_format_docker_update_missing_socket_reply() -> None:
    reply = format_docker_update_reply(
        container_name="ironsbot",
        image="murmansk5000/ironsbot:latest",
        result=DockerUpdateResult(ok=False, missing_socket=True),
    )

    assert "Docker socket" in reply
    assert "/重启机器人" in reply


def test_format_docker_update_success_reply() -> None:
    reply = format_docker_update_reply(
        container_name="ironsbot",
        image="murmansk5000/ironsbot:latest",
        result=DockerUpdateResult(
            ok=True,
            updater_container_id="1234567890abcdef",
            current_image_id="sha256:old-image-id",
            current_image_created="2026-07-04T17:00:00.123456789Z",
            current_image_commit="oldcommitabc old change",
            target_image_id="sha256:new-image-id",
            target_image_created="2026-07-04T18:00:00.987654321Z",
            target_image_commit="newcommitabc new change",
        ),
    )

    assert "Docker 自更新任务已启动" in reply
    assert "murmansk5000/ironsbot:latest" in reply
    assert "当前镜像ID" in reply
    assert "最新镜像ID" in reply
    assert "old-image-id" in reply
    assert "new-image-id" in reply
    assert "2026-07-05 01:00:00" in reply
    assert "2026-07-05 02:00:00" in reply
    assert "oldcommitabc old change" in reply
    assert "newcommitabc new change" in reply
    assert "1234567890ab" not in reply


def test_format_docker_update_hides_bare_commit_hash() -> None:
    reply = format_docker_update_reply(
        container_name="ironsbot",
        image="murmansk5000/ironsbot:latest",
        result=DockerUpdateResult(
            ok=True,
            updater_container_id="1234567890abcdef",
            current_image_id="sha256:old-image-id",
            current_image_created="2026-07-04T17:00:00.123456789Z",
            current_image_commit="744defcda623",
            target_image_id="sha256:new-image-id",
            target_image_created="2026-07-04T18:00:00.987654321Z",
            target_image_commit="6d71db0151c0",
        ),
    )

    assert "当前提交" not in reply
    assert "最新提交" not in reply
    assert "744defcda623" not in reply
    assert "6d71db0151c0" not in reply


def test_format_docker_update_up_to_date_reply() -> None:
    reply = format_docker_update_reply(
        container_name="ironsbot",
        image="murmansk5000/ironsbot:latest",
        result=DockerUpdateResult(
            ok=True,
            up_to_date=True,
            target_image_id="sha256:same-image-id",
            target_image_created="2026-07-04T18:00:00.987654321Z",
            target_image_commit="commitabcdef updated docs",
        ),
    )

    assert "Docker 镜像已是最新" in reply
    assert "same-image-i" in reply
    assert "2026-07-05 02:00:00" in reply
    assert "commitabcdef updated docs" in reply
    assert "Watchtower" not in reply


def test_format_docker_image_created_trims_nanoseconds() -> None:
    assert (
        format_docker_image_created("2026-07-05T00:39:31.108791051Z")
        == "2026-07-05 08:39:31"
    )


def test_create_watchtower_container_sets_docker_api_version() -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"Id": "watchtower-container-id"}

    class FakeClient:
        request_json: dict[str, object] | None = None

        async def post(self, _url: str, **kwargs: object) -> FakeResponse:
            self.request_json = kwargs["json"]  # type: ignore[assignment]
            return FakeResponse()

    client = FakeClient()

    container_id = asyncio.run(
        create_watchtower_container(
            client,  # type: ignore[arg-type]
            container_name="ironsbot",
            socket_path="/var/run/docker.sock",
            watchtower=WatchtowerUpdateOptions(
                image="containrrr/watchtower:latest",
                docker_api_version="1.40",
            ),
        )
    )

    assert container_id == "watchtower-container-id"
    assert client.request_json is not None
    assert client.request_json["Env"] == ["DOCKER_API_VERSION=1.40"]


def test_watchtower_pull_failure_uses_cached_local_image() -> None:
    image = "containrrr/watchtower:latest"

    class FakeClient:
        async def post(self, _url: str, **_kwargs: object) -> httpx.Response:
            return httpx.Response(
                500,
                json={"message": "registry temporarily unavailable"},
                request=httpx.Request("POST", "http://docker/images/create"),
            )

        async def get(self, _url: str) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "Id": "sha256:cached-watchtower",
                    "Created": "2026-07-01T00:00:00Z",
                    "Config": {"Labels": {}},
                },
                request=httpx.Request("GET", "http://docker/images/watchtower/json"),
            )

    result = asyncio.run(
        ensure_watchtower_image(FakeClient(), image)  # type: ignore[arg-type]
    )

    assert result.image_id == "sha256:cached-watchtower"


def test_target_image_pull_failure_includes_docker_error_detail() -> None:
    class FakeClient:
        async def post(self, _url: str, **_kwargs: object) -> httpx.Response:
            return httpx.Response(
                500,
                json={"message": "denied: registry authentication required"},
                request=httpx.Request("POST", "http://docker/images/create"),
            )

    with pytest.raises(
        RuntimeError,
        match="denied: registry authentication required",
    ):
        asyncio.run(
            pull_docker_image(
                FakeClient(),  # type: ignore[arg-type]
                "murmansk5000/ironsbot:latest",
            )
        )


def test_target_image_pull_retries_transient_registry_eof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_attempts = 2
    sleep_delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_delays.append(delay)

    monkeypatch.setattr(
        "ironsbot.integrations.docker.client.asyncio.sleep",
        fake_sleep,
    )

    class FakeClient:
        post_count = 0

        async def post(self, _url: str, **_kwargs: object) -> httpx.Response:
            self.post_count += 1
            if self.post_count == 1:
                return httpx.Response(
                    500,
                    json={
                        "message": (
                            'Get "https://registry-1.docker.io/v2/": EOF'
                        )
                    },
                    request=httpx.Request(
                        "POST",
                        "http://docker/images/create",
                    ),
                )
            return httpx.Response(
                200,
                json={},
                request=httpx.Request("POST", "http://docker/images/create"),
            )

        async def get(self, _url: str) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "Id": "sha256:target-image",
                    "Created": "2026-07-01T00:00:00Z",
                    "Config": {"Labels": {}},
                },
                request=httpx.Request("GET", "http://docker/images/json"),
            )

    client = FakeClient()

    result = asyncio.run(
        pull_docker_image(
            client,  # type: ignore[arg-type]
            "murmansk5000/ironsbot:latest",
        )
    )

    assert result.image_id == "sha256:target-image"
    assert client.post_count == expected_attempts
    assert sleep_delays == [2.0]


def test_docker_update_runtime_is_registered_before_data_sync() -> None:
    lifecycle = ApplicationLifecycle.from_plugins(
        cast("Driver", object()),
        build_test_plugin_registry(),
        task_owner=TaskOwner(),
    )
    names = [name for name, _hook in lifecycle.startup_hooks]

    assert names.index("docker_update") < names.index("db_sync")


def test_startup_docker_update_disabled() -> None:
    notice = asyncio.run(
        build_docker_service(
            DockerUpdateConfig(check_on_startup=False)
        ).startup_notice()
    )

    assert notice is None


def test_startup_docker_update_records_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(_self: object) -> tuple[str, DockerUpdateResult]:
        return (
            "ironsbot-prod",
            DockerUpdateResult(ok=True, updater_container_id="abcdef123456"),
        )

    config = DockerUpdateConfig(
        check_on_startup=True,
        container_name="ironsbot",
        image="murmansk5000/ironsbot:latest",
        docker_socket_path="/var/run/docker.sock",
        watchtower_image="containrrr/watchtower:latest",
        watchtower_docker_api_version="1.40",
        timeout_seconds=300.0,
    )
    monkeypatch.setattr(DockerUpdateService, "run_update", fake_run)

    notice = asyncio.run(
        build_docker_service(config).startup_notice()
    )

    assert notice is not None
    assert "ironsbot-prod" in notice
    assert "Docker 自更新任务已启动" in notice


def test_docker_service_without_restart_check_uses_process_without_socket() -> None:
    service = build_docker_service(
        DockerUpdateConfig(check_on_restart=False)
    )

    message, restart_action = asyncio.run(service.prepare_manual_restart())

    assert restart_action == "process"
    assert "正在重启机器人进程" in message


def test_docker_service_without_restart_check_uses_docker_socket(
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "docker.sock"
    socket_path.touch()
    service = build_docker_service(
        DockerUpdateConfig(
            check_on_restart=False,
            docker_socket_path=str(socket_path),
        )
    )

    message, restart_action = asyncio.run(service.prepare_manual_restart())

    assert restart_action == "docker"
    assert "正在重启机器人容器" in message
    assert "未启用重启前镜像检查" in message


def test_docker_service_missing_socket_continues_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(_self: object) -> tuple[str, DockerUpdateResult]:
        return "ironsbot", DockerUpdateResult(ok=False, missing_socket=True)

    monkeypatch.setattr(DockerUpdateService, "run_update", fake_run)
    service = build_docker_service(
        DockerUpdateConfig(
            check_on_restart=True,
            image="murmansk5000/ironsbot:latest",
        )
    )

    message, restart_action = asyncio.run(service.prepare_manual_restart())

    assert restart_action == "process"
    assert "跳过镜像检查并继续普通进程重启" in message


def test_docker_service_up_to_date_continues_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(_self: object) -> tuple[str, DockerUpdateResult]:
        return "ironsbot", DockerUpdateResult(ok=True, up_to_date=True)

    monkeypatch.setattr(DockerUpdateService, "run_update", fake_run)
    service = build_docker_service(
        DockerUpdateConfig(
            check_on_restart=True,
            image="murmansk5000/ironsbot:latest",
        )
    )

    message, restart_action = asyncio.run(service.prepare_manual_restart())

    assert restart_action == "docker"
    assert "镜像已是最新，正在重启当前容器" in message


def test_docker_service_started_update_skips_extra_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(_self: object) -> tuple[str, DockerUpdateResult]:
        return "ironsbot", DockerUpdateResult(
            ok=True,
            updater_container_id="abcdef123456",
        )

    monkeypatch.setattr(DockerUpdateService, "run_update", fake_run)
    service = build_docker_service(
        DockerUpdateConfig(
            check_on_restart=True,
            image="murmansk5000/ironsbot:latest",
        )
    )

    message, restart_action = asyncio.run(service.prepare_manual_restart())

    assert restart_action == "none"
    assert "Docker 自更新任务已启动" in message
