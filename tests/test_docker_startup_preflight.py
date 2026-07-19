from __future__ import annotations

import asyncio
from pathlib import Path

from ironsbot.config.models.operations import DockerUpdateConfig
from ironsbot.services.operations.docker_models import DockerUpdateResult
from ironsbot.services.operations.docker_preflight import (
    DockerStartupPreflightAction,
    DockerStartupPreflightRecord,
    DockerStartupPreflightService,
    DockerStartupPreflightStore,
    consume_docker_startup_preflight_notice,
)


class FakeUpdateRunner:
    def __init__(
        self,
        result: DockerUpdateResult | Exception,
        *,
        container_name: str = "ironsbot",
    ) -> None:
        self._result = result
        self._container_name = container_name
        self.calls = 0

    async def run_update(self) -> tuple[str, DockerUpdateResult]:
        self.calls += 1
        if isinstance(self._result, Exception):
            raise self._result
        return self._container_name, self._result


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
            ),
            source_instance_id="old-container",
        )
    )
    runner = FakeUpdateRunner(AssertionError("must not check twice"))

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
    notice = consume_docker_startup_preflight_notice(store)
    assert notice is not None
    assert "Docker 自更新任务已启动" in notice


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
    assert 'exec "$@"' in entrypoint
