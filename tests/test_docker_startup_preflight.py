from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import tomli

from ironsbot.app import docker_preflight
from ironsbot.app.docker_preflight import (
    STARTUP_PREFLIGHT_TIMEOUT_SECONDS,
    run_startup_preflight,
    startup_preflight_config,
)
from ironsbot.config.models.operations import (
    DockerUpdateConfig,
    PrivateExtensionsConfig,
)
from ironsbot.services.operations.docker_models import DockerUpdateResult
from ironsbot.services.operations.docker_preflight import (
    DockerStartupPreflightAction,
    DockerStartupPreflightRecord,
    DockerStartupPreflightService,
    DockerStartupPreflightStore,
    consume_docker_startup_preflight_notice,
)

if TYPE_CHECKING:
    import pytest

    from ironsbot.config.models.settings import Settings

MANUAL_DOCKER_TIMEOUT_SECONDS = 300.0


class FakeUpdateRunner:
    def __init__(
        self,
        result: DockerUpdateResult | Exception,
        *,
        container_name: str = "ironsbot",
        handoff_verified: bool = False,
    ) -> None:
        self._result = result
        self._container_name = container_name
        self._handoff_verified = handoff_verified
        self.calls = 0
        self.handoff_checks: list[tuple[str, str]] = []
        self.abandoned_updaters: list[str] = []

    async def run_update(self) -> tuple[str, DockerUpdateResult]:
        self.calls += 1
        if isinstance(self._result, Exception):
            raise self._result
        return self._container_name, self._result

    async def confirm_update_handoff(
        self,
        *,
        expected_image_id: str,
        updater_container_id: str,
    ) -> bool:
        self.handoff_checks.append((expected_image_id, updater_container_id))
        return self._handoff_verified

    async def abandon_update_handoff(
        self,
        *,
        updater_container_id: str,
    ) -> None:
        self.abandoned_updaters.append(updater_container_id)


def _store(tmp_path: Path) -> DockerStartupPreflightStore:
    return DockerStartupPreflightStore(tmp_path / "docker-preflight.json")


def test_disabled_preflight_clears_stale_notice_without_running_update(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.save(
        DockerStartupPreflightRecord(
            container_name="ironsbot",
            image="example/ironsbot:latest",
            result=DockerUpdateResult(ok=True, up_to_date=True),
        )
    )
    runner = FakeUpdateRunner(AssertionError("must not run"))

    action = asyncio.run(
        DockerStartupPreflightService(
            DockerUpdateConfig(check_on_startup=False),
            runner,
            store,
        ).run()
    )

    assert action is DockerStartupPreflightAction.CONTINUE
    assert runner.calls == 0
    assert consume_docker_startup_preflight_notice(store) is None


def test_preflight_persists_one_up_to_date_notice(tmp_path: Path) -> None:
    store = _store(tmp_path)
    runner = FakeUpdateRunner(
        DockerUpdateResult(
            ok=True,
            up_to_date=True,
            target_image_id="sha256:target",
        ),
        container_name="ironsbot-prod",
    )

    action = asyncio.run(
        DockerStartupPreflightService(DockerUpdateConfig(), runner, store).run()
    )

    assert action is DockerStartupPreflightAction.CONTINUE
    notice = consume_docker_startup_preflight_notice(store)
    assert notice is not None
    assert "ironsbot-prod" in notice
    assert "Docker 镜像已是最新" in notice
    assert consume_docker_startup_preflight_notice(store) is None


def test_preflight_waits_when_watchtower_update_started(tmp_path: Path) -> None:
    store = _store(tmp_path)
    runner = FakeUpdateRunner(
        DockerUpdateResult(
            ok=True,
            updater_container_id="watchtower-id",
            current_image_id="sha256:old",
            target_image_id="sha256:new",
        )
    )

    action = asyncio.run(
        DockerStartupPreflightService(DockerUpdateConfig(), runner, store).run()
    )

    assert action is DockerStartupPreflightAction.WAIT_FOR_WATCHTOWER
    notice = consume_docker_startup_preflight_notice(store)
    assert notice is not None
    assert "Docker 自更新任务已启动" in notice


def test_recreated_container_reuses_watchtower_handoff_notice(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(
        DockerStartupPreflightRecord(
            container_name="ironsbot",
            image="murmansk5000/ironsbot:latest",
            result=DockerUpdateResult(
                ok=True,
                updater_container_id="watchtower-id",
                target_image_id="sha256:new",
            ),
            source_instance_id="old-container",
        )
    )
    runner = FakeUpdateRunner(
        AssertionError("must not check twice"),
        handoff_verified=True,
    )

    action = asyncio.run(
        DockerStartupPreflightService(
            DockerUpdateConfig(),
            runner,
            store,
            instance_id="new-container",
        ).run()
    )

    assert action is DockerStartupPreflightAction.CONTINUE
    assert runner.calls == 0
    assert runner.handoff_checks == [("sha256:new", "watchtower-id")]
    notice = consume_docker_startup_preflight_notice(store)
    assert notice is not None
    assert "Docker 镜像已更新完成" in notice


def test_unverified_handoff_retries_watchtower_and_keeps_boot_blocked(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.save(
        DockerStartupPreflightRecord(
            container_name="ironsbot",
            image="murmansk5000/ironsbot:latest",
            result=DockerUpdateResult(
                ok=True,
                updater_container_id="old-watchtower-id",
                target_image_id="sha256:expected",
            ),
        )
    )
    runner = FakeUpdateRunner(
        DockerUpdateResult(
            ok=True,
            updater_container_id="new-watchtower-id",
            current_image_id="sha256:old",
            target_image_id="sha256:expected",
        )
    )

    action = asyncio.run(
        DockerStartupPreflightService(DockerUpdateConfig(), runner, store).run()
    )

    assert action is DockerStartupPreflightAction.WAIT_FOR_WATCHTOWER
    assert runner.calls == 1
    assert runner.handoff_checks == [("sha256:expected", "old-watchtower-id")]


def test_source_instance_waits_without_restarting_watchtower(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(
        DockerStartupPreflightRecord(
            container_name="ironsbot",
            image="murmansk5000/ironsbot:latest",
            result=DockerUpdateResult(
                ok=True,
                updater_container_id="watchtower-id",
                target_image_id="sha256:expected",
            ),
            source_instance_id="old-container",
            created_at=1_000.0,
        )
    )
    runner = FakeUpdateRunner(
        AssertionError("source instance must not start another Watchtower")
    )

    action = asyncio.run(
        DockerStartupPreflightService(
            DockerUpdateConfig(),
            runner,
            store,
            instance_id="old-container",
            now=lambda: 1_030.0,
        ).run()
    )

    assert action is DockerStartupPreflightAction.WAIT_FOR_WATCHTOWER
    assert runner.calls == 0
    assert runner.handoff_checks == [("sha256:expected", "watchtower-id")]
    assert runner.abandoned_updaters == []


def test_source_instance_falls_back_after_handoff_timeout(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(
        DockerStartupPreflightRecord(
            container_name="ironsbot",
            image="murmansk5000/ironsbot:latest",
            result=DockerUpdateResult(
                ok=True,
                updater_container_id="watchtower-id",
                current_image_id="sha256:current",
                target_image_id="sha256:expected",
            ),
            source_instance_id="old-container",
            created_at=1_000.0,
        )
    )
    runner = FakeUpdateRunner(AssertionError("must not restart Watchtower"))

    action = asyncio.run(
        DockerStartupPreflightService(
            DockerUpdateConfig(handoff_timeout_seconds=90.0),
            runner,
            store,
            instance_id="old-container",
            now=lambda: 1_091.0,
        ).run()
    )

    assert action is DockerStartupPreflightAction.CONTINUE
    assert runner.calls == 0
    assert runner.abandoned_updaters == ["watchtower-id"]
    notice = consume_docker_startup_preflight_notice(store)
    assert notice is not None
    assert "等待 Watchtower 交接超时" in notice
    assert "已继续启动当前镜像" in notice


def test_unverified_handoff_failure_allows_current_image_boot(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(
        DockerStartupPreflightRecord(
            container_name="ironsbot",
            image="murmansk5000/ironsbot:latest",
            result=DockerUpdateResult(
                ok=True,
                updater_container_id="watchtower-id",
                target_image_id="sha256:expected",
            ),
        )
    )
    runner = FakeUpdateRunner(DockerUpdateResult(ok=False, message="pull failed"))

    action = asyncio.run(
        DockerStartupPreflightService(DockerUpdateConfig(), runner, store).run()
    )

    assert action is DockerStartupPreflightAction.CONTINUE
    assert runner.calls == 1
    assert runner.abandoned_updaters == ["watchtower-id"]
    notice = consume_docker_startup_preflight_notice(store)
    assert notice is not None
    assert "pull failed" in notice
    assert "已继续启动当前镜像" in notice


def test_handoff_failure_keeps_waiting_when_fallback_is_disabled(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.save(
        DockerStartupPreflightRecord(
            container_name="ironsbot",
            image="murmansk5000/ironsbot:latest",
            result=DockerUpdateResult(
                ok=True,
                updater_container_id="watchtower-id",
                target_image_id="sha256:expected",
            ),
        )
    )
    runner = FakeUpdateRunner(DockerUpdateResult(ok=False, message="pull failed"))

    action = asyncio.run(
        DockerStartupPreflightService(
            DockerUpdateConfig(fallback_to_current_image_on_handoff_failure=False),
            runner,
            store,
        ).run()
    )

    assert action is DockerStartupPreflightAction.WAIT_FOR_WATCHTOWER
    assert runner.calls == 1
    assert runner.abandoned_updaters == []


def test_preflight_records_failure_and_allows_boot(tmp_path: Path) -> None:
    store = _store(tmp_path)
    runner = FakeUpdateRunner(RuntimeError("registry unavailable"))

    action = asyncio.run(
        DockerStartupPreflightService(DockerUpdateConfig(), runner, store).run()
    )

    assert action is DockerStartupPreflightAction.CONTINUE
    notice = consume_docker_startup_preflight_notice(store)
    assert notice is not None
    assert "registry unavailable" in notice


def test_docker_image_runs_preflight_before_application() -> None:
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (root / "docker-entrypoint.sh").read_text(encoding="utf-8")
    dockerignore = (root / ".dockerignore").read_text(encoding="utf-8")

    assert 'ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]' in dockerfile
    assert 'CMD ["python", "-m", "ironsbot"]' in dockerfile
    assert "COPY ironsbot /app/ironsbot" in dockerfile
    assert "COPY LICENSE LICENSE.GPL-3.0 LICENSING.md /app/" in dockerfile
    for notice in ("LICENSE", "LICENSE.GPL-3.0", "LICENSING.md"):
        assert (root / notice).is_file()
        assert notice not in dockerignore.splitlines()
    assert "LICENSE*" not in dockerignore.splitlines()
    assert "COPY . /app/" not in dockerfile
    assert "ENV PYTHONDONTWRITEBYTECODE=1" in dockerfile
    assert "pip install --no-cache-dir --no-compile" in dockerfile
    assert "uv export --frozen --no-dev" in dockerfile
    assert dockerfile.startswith("# syntax=docker/dockerfile:1\n")
    assert "COPY --from=requirements_stage /wheel" not in dockerfile
    assert (
        "RUN --mount=type=bind,from=requirements_stage,source=/wheel,target=/wheel"
        in dockerfile
    )
    assert "rm -rf /wheel" not in dockerfile
    assert "/site-packages/pip" in dockerfile
    assert "/site-packages/setuptools" in dockerfile
    assert "/site-packages/wheel" in dockerfile
    assert ".venv/" in dockerignore
    assert ".codex/" in dockerignore
    assert "**/__pycache__/" in dockerignore
    assert "**/*.py[cod]" in dockerignore
    assert ".pytest_cache/" in dockerignore
    assert "ENV TZ=Asia/Shanghai" in dockerfile
    for repository_only_path in (
        "data/",
        "docker/",
        "docs/",
        "scripts/",
        "tables/",
        "tables_custom/",
        "templates/",
        "tests/",
    ):
        assert repository_only_path in dockerignore
    assert "python -m ironsbot.app.docker_preflight" in entrypoint
    assert 'while [ "$preflight_status" -eq 75 ]; do' in entrypoint
    assert "while :; do" not in entrypoint
    wait_offset = entrypoint.index('while [ "$preflight_status" -eq 75 ]; do')
    app_start_offset = entrypoint.index('exec "$@"')
    assert wait_offset < app_start_offset
    assert "run_preflight" in entrypoint[wait_offset:app_start_offset]
    assert 'exec "$@"' in entrypoint


def test_runtime_server_uses_only_declared_protocol_dependencies() -> None:
    root = Path(__file__).resolve().parents[1]
    project = tomli.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomli.loads((root / "uv.lock").read_text(encoding="utf-8"))
    main = (root / "ironsbot" / "__main__.py").read_text(encoding="utf-8")

    dependencies = project["project"]["dependencies"]
    assert "nonebot2[httpx]>=2.4.4" in dependencies
    assert not any(
        dependency.startswith("nonebot2[fastapi") for dependency in dependencies
    )
    assert "fastapi>=0.93.0,<1.0.0" in dependencies
    assert "uvicorn>=0.20.0,<1.0.0" in dependencies
    assert "websockets>=15.0" in dependencies

    locked_names = {package["name"] for package in lock["package"]}
    assert {"fastapi", "uvicorn", "websockets"} <= locked_names
    assert locked_names.isdisjoint({"httptools", "uvloop", "watchfiles"})

    assert 'loop="asyncio"' in main
    assert 'http="h11"' in main
    assert 'ws="websockets-sansio"' in main


def test_startup_preflight_timeout_is_shorter_than_manual_update_timeout() -> None:
    config = DockerUpdateConfig(timeout_seconds=MANUAL_DOCKER_TIMEOUT_SECONDS)

    assert config.timeout_seconds > STARTUP_PREFLIGHT_TIMEOUT_SECONDS
    assert (
        startup_preflight_config(config).timeout_seconds
        == STARTUP_PREFLIGHT_TIMEOUT_SECONDS
    )
    assert config.timeout_seconds == MANUAL_DOCKER_TIMEOUT_SECONDS


def test_startup_preflight_refreshes_private_extensions_after_image_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_docker_preflight(_config: DockerUpdateConfig):
        calls.append("docker")
        return DockerStartupPreflightAction.CONTINUE

    async def fake_extension_preflight(
        _config: PrivateExtensionsConfig,
        _docker_update: DockerUpdateConfig,
    ) -> None:
        calls.append("extensions")

    monkeypatch.setattr(
        docker_preflight,
        "run_docker_startup_preflight",
        fake_docker_preflight,
    )
    monkeypatch.setattr(
        docker_preflight,
        "run_private_extensions_preflight",
        fake_extension_preflight,
    )
    settings = SimpleNamespace(
        operations=SimpleNamespace(
            docker_update=DockerUpdateConfig(),
            private_extensions=PrivateExtensionsConfig(enabled=True),
        )
    )

    action = asyncio.run(run_startup_preflight(cast("Settings", settings)))

    assert action is DockerStartupPreflightAction.CONTINUE
    assert calls == ["docker", "extensions"]


def test_startup_preflight_skips_extension_refresh_during_update_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_docker_preflight(_config: DockerUpdateConfig):
        calls.append("docker")
        return DockerStartupPreflightAction.WAIT_FOR_WATCHTOWER

    async def fake_extension_preflight(
        _config: PrivateExtensionsConfig,
        _docker_update: DockerUpdateConfig,
    ) -> None:
        calls.append("extensions")

    monkeypatch.setattr(
        docker_preflight,
        "run_docker_startup_preflight",
        fake_docker_preflight,
    )
    monkeypatch.setattr(
        docker_preflight,
        "run_private_extensions_preflight",
        fake_extension_preflight,
    )
    settings = SimpleNamespace(
        operations=SimpleNamespace(
            docker_update=DockerUpdateConfig(),
            private_extensions=PrivateExtensionsConfig(enabled=True),
        )
    )

    action = asyncio.run(run_startup_preflight(cast("Settings", settings)))

    assert action is DockerStartupPreflightAction.WAIT_FOR_WATCHTOWER
    assert calls == ["docker"]
