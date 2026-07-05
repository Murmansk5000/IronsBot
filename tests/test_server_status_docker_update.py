import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from ironsbot.app.plugin_manifest import RUNTIME_SETUP_CALLS
from ironsbot.plugins.server_status import (
    DockerUpdateResult,
    RestartService,
    WatchtowerUpdateOptions,
    _create_watchtower_container,
    _format_docker_image_created,
    _format_docker_update_reply,
    _resolve_docker_container_name,
    _split_docker_image,
)
from ironsbot.plugins.server_status import runtime as docker_update_runtime


def test_split_docker_image_with_tag() -> None:
    assert _split_docker_image("containrrr/watchtower:latest") == (
        "containrrr/watchtower",
        "latest",
    )


def test_split_docker_image_defaults_latest() -> None:
    assert _split_docker_image("containrrr/watchtower") == (
        "containrrr/watchtower",
        "latest",
    )


def test_resolve_container_name_prefers_unraid_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOST_CONTAINERNAME", "ironsbot-prod")

    assert _resolve_docker_container_name("ironsbot") == "ironsbot-prod"


def test_format_docker_update_missing_socket_reply() -> None:
    reply = _format_docker_update_reply(
        container_name="ironsbot",
        image="murmansk5000/ironsbot:latest",
        result=DockerUpdateResult(ok=False, missing_socket=True),
    )

    assert "Docker socket" in reply
    assert "/重启机器人" in reply


def test_format_docker_update_success_reply() -> None:
    reply = _format_docker_update_reply(
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
    assert "当前镜像版本" in reply
    assert "最新镜像版本" in reply
    assert "old-image-id" in reply
    assert "new-image-id" in reply
    assert "2026-07-05 01:00:00" in reply
    assert "2026-07-05 02:00:00" in reply
    assert "oldcommitabc old change" in reply
    assert "newcommitabc new change" in reply
    assert "1234567890ab" not in reply


def test_format_docker_update_up_to_date_reply() -> None:
    reply = _format_docker_update_reply(
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
        _format_docker_image_created("2026-07-05T00:39:31.108791051Z")
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
        _create_watchtower_container(
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


def test_docker_update_runtime_is_registered_before_data_sync() -> None:
    assert RUNTIME_SETUP_CALLS[0] == (
        "ironsbot.plugins.server_status.runtime:setup_docker_update_runtime"
    )
    assert RUNTIME_SETUP_CALLS[1] == (
        "ironsbot.plugins.db_sync.runtime:setup_db_sync_runtime"
    )


def test_startup_docker_update_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        docker_update_runtime,
        "get_docker_update_config",
        lambda: SimpleNamespace(check_on_startup=False),
    )

    asyncio.run(docker_update_runtime._start_docker_update_runtime())

    assert docker_update_runtime.get_startup_docker_update_notice() is None


def test_startup_docker_update_records_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_update(**_kwargs: object) -> DockerUpdateResult:
        return DockerUpdateResult(ok=True, updater_container_id="abcdef123456")

    from ironsbot.plugins import server_status

    monkeypatch.setattr(
        docker_update_runtime,
        "get_docker_update_config",
        lambda: SimpleNamespace(
            check_on_startup=True,
            container_name="ironsbot",
            image="murmansk5000/ironsbot:latest",
            docker_socket_path="/var/run/docker.sock",
            watchtower_image="containrrr/watchtower:latest",
            watchtower_docker_api_version="1.40",
            timeout_seconds=300.0,
        ),
    )
    monkeypatch.setattr(server_status, "_start_watchtower_update", fake_update)
    monkeypatch.setattr(
        server_status,
        "_resolve_docker_container_name",
        lambda _name: "ironsbot-prod",
    )

    asyncio.run(docker_update_runtime._start_docker_update_runtime())

    notice = docker_update_runtime.get_startup_docker_update_notice()
    assert notice is not None
    assert "ironsbot-prod" in notice
    assert "Docker 自更新任务已启动" in notice


def test_restart_service_without_restart_check_uses_process_without_socket() -> None:
    service = RestartService(SimpleNamespace(check_on_restart=False))

    message, restart_action = asyncio.run(service.prepare_manual_restart())

    assert restart_action == "process"
    assert "正在重启机器人进程" in message


def test_restart_service_without_restart_check_uses_docker_socket(
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "docker.sock"
    socket_path.touch()
    service = RestartService(
        SimpleNamespace(
            check_on_restart=False,
            docker_socket_path=str(socket_path),
        )
    )

    message, restart_action = asyncio.run(service.prepare_manual_restart())

    assert restart_action == "docker"
    assert "正在重启机器人容器" in message
    assert "未启用重启前镜像检查" in message


def test_restart_service_missing_socket_continues_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(_self: object) -> tuple[str, DockerUpdateResult]:
        return "ironsbot", DockerUpdateResult(ok=False, missing_socket=True)

    from ironsbot.plugins.server_status import DockerSelfUpdateService

    monkeypatch.setattr(DockerSelfUpdateService, "run", fake_run)
    service = RestartService(
        SimpleNamespace(
            check_on_restart=True,
            image="murmansk5000/ironsbot:latest",
        )
    )

    message, restart_action = asyncio.run(service.prepare_manual_restart())

    assert restart_action == "process"
    assert "跳过镜像检查并继续普通进程重启" in message


def test_restart_service_up_to_date_continues_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(_self: object) -> tuple[str, DockerUpdateResult]:
        return "ironsbot", DockerUpdateResult(ok=True, up_to_date=True)

    from ironsbot.plugins.server_status import DockerSelfUpdateService

    monkeypatch.setattr(DockerSelfUpdateService, "run", fake_run)
    service = RestartService(
        SimpleNamespace(
            check_on_restart=True,
            image="murmansk5000/ironsbot:latest",
        )
    )

    message, restart_action = asyncio.run(service.prepare_manual_restart())

    assert restart_action == "docker"
    assert "镜像已是最新，正在重启当前容器" in message


def test_restart_service_started_update_skips_extra_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(_self: object) -> tuple[str, DockerUpdateResult]:
        return "ironsbot", DockerUpdateResult(
            ok=True,
            updater_container_id="abcdef123456",
        )

    from ironsbot.plugins.server_status import DockerSelfUpdateService

    monkeypatch.setattr(DockerSelfUpdateService, "run", fake_run)
    service = RestartService(
        SimpleNamespace(
            check_on_restart=True,
            image="murmansk5000/ironsbot:latest",
        )
    )

    message, restart_action = asyncio.run(service.prepare_manual_restart())

    assert restart_action == "none"
    assert "Docker 自更新任务已启动" in message
