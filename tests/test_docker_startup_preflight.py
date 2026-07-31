from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

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
        ).run()
    )

    assert action is DockerStartupPreflightAction.WAIT_FOR_WATCHTOWER
    assert runner.calls == 0
    assert runner.handoff_checks == [("sha256:expected", "watchtower-id")]


def test_unverified_handoff_failure_keeps_boot_blocked(tmp_path: Path) -> None:
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

    assert action is DockerStartupPreflightAction.WAIT_FOR_WATCHTOWER
    assert runner.calls == 1


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

    assert 'ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]' in dockerfile
    assert 'CMD ["python", "-m", "ironsbot"]' in dockerfile
    assert "python -m ironsbot.app.docker_preflight" in entrypoint
    assert "while :; do" in entrypoint
    wait_offset = entrypoint.index("while :; do")
    app_start_offset = entrypoint.index('exec "$@"')
    assert wait_offset < app_start_offset
    assert "break" not in entrypoint[wait_offset:app_start_offset]
    assert 'exec "$@"' in entrypoint


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
