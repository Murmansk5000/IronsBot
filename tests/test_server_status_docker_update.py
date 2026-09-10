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
    inspect_registry_image_info,
    inspect_remote_image_digest,
    pull_docker_image,
    split_docker_image,
)
from ironsbot.services.operations.docker_formatting import (
    format_docker_image_check_reply,
    format_docker_image_created,
    format_docker_update_handoff_reply,
    format_docker_update_reply,
)
from ironsbot.services.operations.docker_models import (
    DockerImageCheckResult,
    DockerImageInfo,
    DockerRegistryCredentials,
    DockerUpdateRequest,
    DockerUpdateResult,
    WatchtowerUpdateOptions,
)
from ironsbot.services.operations.docker_preflight import DockerStartupPreflightStore
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


def test_format_docker_update_handoff_reply_confirms_verified_target() -> None:
    reply = format_docker_update_handoff_reply(
        container_name="ironsbot",
        image="murmansk5000/ironsbot:latest",
        result=DockerUpdateResult(
            ok=True,
            updater_container_id="watchtower-id",
            current_image_id="sha256:old-image-id",
            target_image_id="sha256:new-image-id",
            target_image_created="2026-07-04T18:00:00.987654321Z",
            target_image_commit="newcommitabc new change",
        ),
    )

    assert "Docker 镜像已更新完成" in reply
    assert "Docker 自更新任务已启动" not in reply
    assert "new-image-id" in reply
    assert "newcommitabc new change" in reply


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


def test_format_docker_image_check_does_not_offer_side_effects() -> None:
    reply = format_docker_image_check_reply(
        container_name="ironsbot",
        image="murmansk5000/ironsbot:latest",
        result=DockerImageCheckResult(
            ok=True,
            current_image_id="sha256:current-image-id",
            current_image_created="2026-07-04T18:00:00.987654321Z",
            remote_digest="sha256:remote-manifest-digest",
            remote_image_id="sha256:remote-image-id",
            remote_image_created="2026-07-04T19:00:00.987654321Z",
            current_image_commit="oldcommitabc old change",
            remote_image_commit="newcommitabc new change",
        ),
    )

    assert "检测到新镜像：ironsbot" in reply
    assert "当前镜像ID" in reply
    assert "Docker Hub latest 镜像ID" in reply
    assert "oldcommitabc old change" in reply
    assert "newcommitabc new change" in reply
    assert "2026-07-05 02:00:00" in reply
    assert "2026-07-05 03:00:00" in reply
    assert "等待确认后更新并重启" in reply
    assert "未拉取镜像、未创建 Watchtower、未重启容器" in reply


def test_format_docker_image_check_reports_matching_remote_digest() -> None:
    reply = format_docker_image_check_reply(
        container_name="ironsbot",
        image="murmansk5000/ironsbot:latest",
        result=DockerImageCheckResult(
            ok=True,
            up_to_date=True,
            current_image_id="sha256:current-image-id",
            remote_digest="sha256:remote-manifest-digest",
        ),
    )

    assert "Docker 镜像已是最新" in reply
    assert "未拉取镜像、未创建 Watchtower、未重启容器" in reply


def test_format_docker_image_check_distinguishes_stale_latest_from_main() -> None:
    reply = format_docker_image_check_reply(
        container_name="ironsbot",
        image="murmansk5000/ironsbot:latest",
        result=DockerImageCheckResult(
            ok=True,
            up_to_date=True,
            current_image_id="sha256:current-image-id",
            remote_digest="sha256:remote-manifest-digest",
            current_image_revision="f7fc6546c7ff",
            remote_image_revision="f7fc6546c7ff",
            github_main_revision="499223c8f23ad9be9e3320725ee70a7b77a14ad5",
        ),
    )

    assert "GitHub main：499223c8f23a" in reply
    assert "Docker Hub latest 尚未对齐 GitHub main" in reply
    assert "本机与 Docker Hub latest 一致，但两者均落后 GitHub main" in reply


def test_inspect_registry_image_info_reads_remote_oci_config() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/manifests/latest"):
            return httpx.Response(
                200,
                json={
                    "manifests": [
                        {
                            "digest": "sha256:linux-amd64-manifest",
                            "platform": {"os": "linux", "architecture": "amd64"},
                        }
                    ]
                },
                request=request,
            )
        if request.url.path.endswith("/manifests/sha256:linux-amd64-manifest"):
            return httpx.Response(
                200,
                json={"config": {"digest": "sha256:remote-config"}},
                request=request,
            )
        if request.url.path.endswith("/blobs/sha256:remote-config"):
            return httpx.Response(
                200,
                json={
                    "created": "2026-07-28T10:01:35Z",
                    "config": {
                        "Labels": {
                            "org.opencontainers.image.revision": "deadbeef",
                        }
                    },
                },
                request=request,
            )
        pytest.fail(f"unexpected registry request: {request.url}")

    async def inspect() -> DockerImageInfo:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await inspect_registry_image_info(
                client,
                "murmansk5000/ironsbot:latest",
            )

    result = asyncio.run(inspect())

    assert result.image_id == "sha256:remote-config"
    assert result.created == "2026-07-28T10:01:35Z"
    assert result.labels["org.opencontainers.image.revision"] == "deadbeef"


def test_inspect_remote_image_digest_uses_distribution_endpoint() -> None:
    class FakeClient:
        requested_url = ""

        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            self.requested_url = url
            return httpx.Response(
                200,
                json={"Descriptor": {"digest": "sha256:remote-digest"}},
                request=httpx.Request("GET", f"http://docker{url}"),
            )

    client = FakeClient()
    digest = asyncio.run(
        inspect_remote_image_digest(
            client,  # type: ignore[arg-type]
            "murmansk5000/ironsbot:latest",
        )
    )

    assert digest == "sha256:remote-digest"
    assert client.requested_url.startswith("/distribution/")


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
    assert client.request_json["Cmd"] == ["--run-once", "--cleanup", "ironsbot"]
    host_config = cast("dict[str, object]", client.request_json["HostConfig"])
    assert host_config["AutoRemove"] is False


def test_create_watchtower_container_passes_private_registry_credentials() -> None:
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

    asyncio.run(
        create_watchtower_container(
            client,  # type: ignore[arg-type]
            container_name="ironsbot",
            socket_path="/var/run/docker.sock",
            watchtower=WatchtowerUpdateOptions(
                image="containrrr/watchtower:latest",
                docker_api_version="1.40",
            ),
            registry_credentials=DockerRegistryCredentials(
                username="owner",
                token="registry-token",
            ),
        )
    )

    assert client.request_json is not None
    assert client.request_json["Env"] == [
        "DOCKER_API_VERSION=1.40",
        "REPO_USER=owner",
        "REPO_PASS=registry-token",
    ]


def test_docker_update_service_passes_private_registry_credentials() -> None:
    class FakeDocker:
        request: DockerUpdateRequest | None = None

        async def socket_exists(self, _socket_path: str) -> bool:
            return True

        async def start_update(
            self,
            request: DockerUpdateRequest,
        ) -> DockerUpdateResult:
            self.request = request
            return DockerUpdateResult(ok=True, up_to_date=True)

        async def restart_container(self, **_kwargs: object) -> None:
            return None

    docker = FakeDocker()
    service = DockerUpdateService(
        DockerUpdateConfig(
            registry_username="owner",
            registry_token="registry-token",
        ),
        docker,  # type: ignore[arg-type]
        noop_restart_process,
    )

    asyncio.run(service.run_update())

    assert docker.request is not None
    assert docker.request.registry_credentials == DockerRegistryCredentials(
        username="owner",
        token="registry-token",
    )


def test_docker_update_service_verifies_target_image_before_cleanup() -> None:
    class FakeDocker:
        checked: tuple[str, str] | None = None
        removed: str | None = None

        async def socket_exists(self, _socket_path: str) -> bool:
            return True

        async def container_uses_image(
            self,
            *,
            container_name: str,
            expected_image_id: str,
            socket_path: str,
            timeout_seconds: float,
        ) -> bool:
            assert socket_path == "/var/run/docker.sock"
            assert timeout_seconds > 0
            self.checked = (container_name, expected_image_id)
            return True

        async def remove_container(
            self,
            *,
            container_id: str,
            socket_path: str,
            timeout_seconds: float,
        ) -> None:
            assert socket_path == "/var/run/docker.sock"
            assert timeout_seconds > 0
            self.removed = container_id

    docker = FakeDocker()
    service = DockerUpdateService(
        DockerUpdateConfig(),
        docker,  # type: ignore[arg-type]
        noop_restart_process,
    )

    matched = asyncio.run(
        service.confirm_update_handoff(
            expected_image_id="sha256:target",
            updater_container_id="watchtower-id",
        )
    )

    assert matched is True
    assert docker.checked == ("ironsbot", "sha256:target")
    assert docker.removed == "watchtower-id"


def test_docker_update_service_keeps_watchtower_when_target_image_differs() -> None:
    class FakeDocker:
        removed = False

        async def socket_exists(self, _socket_path: str) -> bool:
            return True

        async def container_uses_image(self, **_kwargs: object) -> bool:
            return False

        async def remove_container(self, **_kwargs: object) -> None:
            self.removed = True

    docker = FakeDocker()
    service = DockerUpdateService(
        DockerUpdateConfig(),
        docker,  # type: ignore[arg-type]
        noop_restart_process,
    )

    matched = asyncio.run(
        service.confirm_update_handoff(
            expected_image_id="sha256:target",
            updater_container_id="watchtower-id",
        )
    )

    assert matched is False
    assert docker.removed is False


def test_docker_update_service_checks_without_starting_an_update() -> None:
    class FakeDocker:
        check_request: DockerUpdateRequest | None = None

        async def socket_exists(self, _socket_path: str) -> bool:
            return True

        async def start_update(
            self,
            _request: DockerUpdateRequest,
        ) -> DockerUpdateResult:
            pytest.fail("image check must not start an update")

        async def check_update(
            self,
            request: DockerUpdateRequest,
        ) -> DockerImageCheckResult:
            self.check_request = request
            return DockerImageCheckResult(
                ok=True,
                up_to_date=True,
                current_image_id="sha256:current-image",
                remote_digest="sha256:remote-digest",
            )

        async def restart_container(self, **_kwargs: object) -> None:
            pytest.fail("image check must not restart the container")

    docker = FakeDocker()
    service = DockerUpdateService(
        DockerUpdateConfig(image="murmansk5000/ironsbot:latest"),
        docker,  # type: ignore[arg-type]
        noop_restart_process,
    )

    reply = asyncio.run(service.check_image_update())

    assert docker.check_request is not None
    assert "Docker 镜像已是最新" in reply
    assert "未拉取镜像、未创建 Watchtower、未重启容器" in reply


def test_manual_docker_update_checks_before_running_the_update() -> None:
    class FakeDocker:
        checks = 0
        starts = 0

        async def socket_exists(self, _socket_path: str) -> bool:
            return True

        async def check_update(
            self,
            _request: DockerUpdateRequest,
        ) -> DockerImageCheckResult:
            self.checks += 1
            return DockerImageCheckResult(
                ok=True,
                current_image_id="sha256:current-image",
                remote_digest="sha256:remote-digest",
                remote_image_id="sha256:remote-image",
            )

        async def start_update(
            self,
            _request: DockerUpdateRequest,
        ) -> DockerUpdateResult:
            self.starts += 1
            return DockerUpdateResult(
                ok=True,
                current_image_id="sha256:current-image",
                target_image_id="sha256:remote-image",
            )

        async def restart_container(self, **_kwargs: object) -> None:
            pytest.fail("manual image update must use the update path")

    docker = FakeDocker()
    service = DockerUpdateService(
        DockerUpdateConfig(image="murmansk5000/ironsbot:latest"),
        docker,  # type: ignore[arg-type]
        noop_restart_process,
    )

    reply, should_update = asyncio.run(service.prepare_manual_update())

    assert should_update
    assert docker.checks == 1
    assert docker.starts == 0
    assert "等待确认后更新并重启" in reply

    asyncio.run(service.execute_manual_update())

    assert docker.starts == 1


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


def test_docker_service_without_restart_check_uses_process_without_socket() -> None:
    service = build_docker_service(
        DockerUpdateConfig(check_on_restart=False)
    )

    message, restart_action = asyncio.run(service.prepare_manual_restart())

    assert restart_action == "process"
    assert "正在重启机器人进程" in message
    assert "仅重启" in message


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
    assert "仅重启" in message


def test_explicit_update_and_restart_ignores_legacy_restart_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(_self: object) -> tuple[str, DockerUpdateResult]:
        return "ironsbot", DockerUpdateResult(ok=True, up_to_date=True)

    monkeypatch.setattr(DockerUpdateService, "run_update", fake_run)
    service = build_docker_service(
        DockerUpdateConfig(
            check_on_restart=False,
            image="murmansk5000/ironsbot:latest",
        )
    )

    message, restart_action = asyncio.run(service.prepare_update_and_restart())

    assert restart_action == "docker"
    assert "镜像已是最新，正在重启当前容器" in message


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


def test_manual_update_records_expected_target_for_recreated_container(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def fake_run(_self: object) -> tuple[str, DockerUpdateResult]:
        return "ironsbot", DockerUpdateResult(
            ok=True,
            updater_container_id="watchtower-id",
            current_image_id="sha256:old",
            target_image_id="sha256:target",
        )

    monkeypatch.setattr(DockerUpdateService, "run_update", fake_run)
    store = DockerStartupPreflightStore(tmp_path / "docker-preflight.json")
    service = DockerUpdateService(
        DockerUpdateConfig(check_on_restart=True),
        DockerClient(),
        noop_restart_process,
        handoff_store=store,
        instance_id="old-container",
    )

    _message, restart_action = asyncio.run(service.prepare_manual_restart())

    record = store.read()
    assert restart_action == "none"
    assert record is not None
    assert record.source_instance_id == "old-container"
    assert record.result.target_image_id == "sha256:target"
    assert record.result.updater_container_id == "watchtower-id"
