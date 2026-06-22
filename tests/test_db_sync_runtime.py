import asyncio
import hashlib
import sqlite3
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import httpx
import nonebot
from pytest import MonkeyPatch
from typing_extensions import Self

from ironsbot.config.models.runtime import RemoteBuildConfig, RemoteBuildStepConfig

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

try:
    nonebot.load_plugin("ironsbot.plugins.db_sync")
except RuntimeError as e:
    if "Plugin already exists" not in str(e):
        raise

from ironsbot.plugins import db_sync
from ironsbot.plugins.db_sync import runtime as db_sync_runtime
from ironsbot.plugins.db_sync.github_actions import WorkflowRunResult

CONNECT_ERROR_MESSAGE = "connection failed"


class FakeDriver:
    def __init__(self) -> None:
        self.startup_handlers: list[Callable[[], object]] = []

    def on_startup(self, handler: Callable[[], object]) -> Callable[[], object]:
        self.startup_handlers.append(handler)
        return handler


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


def test_db_sync_runtime_setup_registers_startup_once(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    monkeypatch.setitem(
        db_sync_runtime._db_sync_runtime_state,
        "registered",
        registered_state,
    )
    driver = FakeDriver()
    scheduler = FakeScheduler()

    db_sync_runtime._setup_db_sync_runtime(driver, scheduler)
    db_sync_runtime._setup_db_sync_runtime(driver, scheduler)

    assert len(driver.startup_handlers) == 1


def test_register_database_defers_engine_and_scheduler_setup(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_engines: list[str] = []
    monkeypatch.setattr(db_sync, "_registered_syncs", {})
    monkeypatch.setattr(db_sync, "_registered_local_databases", {})
    monkeypatch.setattr(db_sync.db_manager, "register", registered_engines.append)

    db_sync.register_database(
        "unit",
        sync_url="https://example.invalid/unit.sqlite",
        sync_interval_minutes=15,
    )

    assert "unit" in db_sync._registered_syncs
    assert registered_engines == []


def test_db_sync_startup_prepares_engines_and_interval_jobs(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_engines: list[str] = []
    scheduler = FakeScheduler()
    monkeypatch.setattr(
        db_sync,
        "_registered_syncs",
        {
            "unit": db_sync._SyncEntry(
                "https://example.invalid/unit.sqlite",
                15,
                None,
                None,
            )
        },
    )
    monkeypatch.setattr(db_sync, "_registered_local_databases", {})
    monkeypatch.setattr(db_sync, "_prepared_databases", set())
    monkeypatch.setattr(db_sync.db_manager, "register", registered_engines.append)
    monkeypatch.setattr(
        db_sync_runtime,
        "get_data_sync_config",
        lambda: SimpleNamespace(interval_enabled=True, on_startup=False),
    )

    asyncio.run(db_sync_runtime._start_db_sync_runtime(scheduler))

    assert registered_engines == ["unit"]
    assert scheduler.jobs == [
        {
            "func": db_sync.run_sync_database,
            "trigger": "interval",
            "args": ["unit"],
            "minutes": 15,
            "id": "db_sync_unit",
            "replace_existing": True,
        }
    ]


def _remote_build_config() -> RemoteBuildConfig:
    return RemoteBuildConfig(
        enabled=True,
        repository="Murmansk5000/seerapi",
        workflow_id="build-ironsbot-data-db.yml",
        ref="main",
        timeout_seconds=1200,
        poll_interval_seconds=10,
    )


def _remote_build_pipeline_config() -> RemoteBuildConfig:
    return RemoteBuildConfig(
        enabled=True,
        steps=[
            RemoteBuildStepConfig(
                name="update_unity_config",
                repository="Murmansk5000/seer-unity-config-parser",
                workflow_id="schedule.yml",
            ),
            RemoteBuildStepConfig(
                name="sync_config_sources",
                repository="Murmansk5000/config-sources",
                workflow_id="sync-upstream.yml",
            ),
            RemoteBuildStepConfig(
                name="build_seer_data",
                repository="Murmansk5000/seer-data",
                workflow_id="main.yml",
            ),
            RemoteBuildStepConfig(
                name="build_ironsbot_data",
                repository="Murmansk5000/seerapi",
                workflow_id="build-ironsbot-data-db.yml",
            ),
        ],
    )


def test_manual_sync_triggers_remote_build_before_download(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        db_sync,
        "_registered_syncs",
        {
            "seerapi": db_sync._SyncEntry(
                "https://example.invalid/seerapi.sqlite",
                60,
                None,
                None,
                _remote_build_config(),
            ),
            "aliases": db_sync._SyncEntry(
                "https://example.invalid/aliases.sqlite",
                60,
                None,
                None,
                None,
            ),
        },
    )
    monkeypatch.setattr(
        db_sync,
        "load_secrets_config",
        lambda: SimpleNamespace(github_workflow_token="token"),
    )

    async def fake_build(
        config: RemoteBuildConfig,
        *,
        token: str,
    ) -> WorkflowRunResult:
        calls.append(f"build:{config.repository}:{token}")
        return WorkflowRunResult(
            ok=True,
            status="completed",
            conclusion="success",
            html_url="https://github.com/Murmansk5000/seerapi/actions/runs/1",
            message="ok",
        )

    async def fake_sync(name: str) -> bool:
        calls.append(f"sync:{name}")
        return True

    monkeypatch.setattr(db_sync, "trigger_and_wait_workflow", fake_build)
    monkeypatch.setattr(db_sync, "sync_database", fake_sync)

    results = asyncio.run(db_sync.sync_all_databases(trigger_remote_build=True))

    assert results == {"seerapi": True, "aliases": True}
    assert calls == [
        "build:Murmansk5000/seerapi:token",
        "sync:seerapi",
        "sync:aliases",
    ]


def test_manual_sync_runs_remote_build_pipeline_before_download(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        db_sync,
        "_registered_syncs",
        {
            "seerapi": db_sync._SyncEntry(
                "https://example.invalid/seerapi.sqlite",
                60,
                None,
                None,
                _remote_build_pipeline_config(),
            ),
        },
    )
    monkeypatch.setattr(
        db_sync,
        "load_secrets_config",
        lambda: SimpleNamespace(github_workflow_token="token"),
    )

    async def fake_build(
        config: RemoteBuildStepConfig,
        *,
        token: str,
    ) -> WorkflowRunResult:
        calls.append(f"build:{config.name}:{config.repository}:{token}")
        return WorkflowRunResult(
            ok=True,
            status="completed",
            conclusion="success",
            html_url=f"https://github.com/{config.repository}/actions/runs/1",
            message="ok",
        )

    async def fake_sync(name: str) -> bool:
        calls.append(f"sync:{name}")
        return True

    monkeypatch.setattr(db_sync, "trigger_and_wait_workflow", fake_build)
    monkeypatch.setattr(db_sync, "sync_database", fake_sync)

    results = asyncio.run(db_sync.sync_all_databases(trigger_remote_build=True))

    assert results == {"seerapi": True}
    assert calls == [
        "build:update_unity_config:Murmansk5000/seer-unity-config-parser:token",
        "build:sync_config_sources:Murmansk5000/config-sources:token",
        "build:build_seer_data:Murmansk5000/seer-data:token",
        "build:build_ironsbot_data:Murmansk5000/seerapi:token",
        "sync:seerapi",
    ]


def test_remote_build_failure_skips_old_release_download(
    monkeypatch: MonkeyPatch,
) -> None:
    synced: list[str] = []
    monkeypatch.setattr(
        db_sync,
        "_registered_syncs",
        {
            "seerapi": db_sync._SyncEntry(
                "https://example.invalid/seerapi.sqlite",
                60,
                None,
                None,
                _remote_build_config(),
            ),
            "aliases": db_sync._SyncEntry(
                "https://example.invalid/aliases.sqlite",
                60,
                None,
                None,
                None,
            ),
        },
    )
    monkeypatch.setattr(
        db_sync,
        "load_secrets_config",
        lambda: SimpleNamespace(github_workflow_token="token"),
    )

    async def fake_build(
        config: RemoteBuildConfig,
        *,
        token: str,
    ) -> WorkflowRunResult:
        return WorkflowRunResult(
            ok=False,
            status="completed",
            conclusion="failure",
            html_url="https://github.com/Murmansk5000/seerapi/actions/runs/1",
            message=f"{config.workflow_id} failed with {token}",
        )

    async def fake_sync(name: str) -> bool:
        synced.append(name)
        return True

    monkeypatch.setattr(db_sync, "trigger_and_wait_workflow", fake_build)
    monkeypatch.setattr(db_sync, "sync_database", fake_sync)

    results = asyncio.run(db_sync.sync_all_databases(trigger_remote_build=True))

    assert results == {"seerapi": False, "aliases": True}
    assert synced == ["aliases"]


def test_scheduled_sync_does_not_trigger_remote_build(
    monkeypatch: MonkeyPatch,
) -> None:
    synced: list[str] = []
    monkeypatch.setattr(
        db_sync,
        "_registered_syncs",
        {
            "seerapi": db_sync._SyncEntry(
                "https://example.invalid/seerapi.sqlite",
                60,
                None,
                None,
                _remote_build_config(),
            )
        },
    )

    async def fail_build(
        _config: RemoteBuildConfig,
        *,
        _token: str,
    ) -> WorkflowRunResult:
        msg = "scheduled sync must not trigger remote build"
        raise AssertionError(msg)

    async def fake_sync(name: str) -> bool:
        synced.append(name)
        return True

    monkeypatch.setattr(db_sync, "trigger_and_wait_workflow", fail_build)
    monkeypatch.setattr(db_sync, "sync_database", fake_sync)

    results = asyncio.run(db_sync.sync_all_databases())

    assert results == {"seerapi": True}
    assert synced == ["seerapi"]


def test_remote_build_enabled_without_token_fails_fast(
    monkeypatch: MonkeyPatch,
) -> None:
    synced: list[str] = []
    monkeypatch.setattr(
        db_sync,
        "_registered_syncs",
        {
            "seerapi": db_sync._SyncEntry(
                "https://example.invalid/seerapi.sqlite",
                60,
                None,
                None,
                _remote_build_config(),
            )
        },
    )
    monkeypatch.setattr(
        db_sync,
        "load_secrets_config",
        lambda: SimpleNamespace(github_workflow_token=""),
    )

    async def fake_sync(name: str) -> bool:
        synced.append(name)
        return True

    monkeypatch.setattr(db_sync, "sync_database", fake_sync)

    results = asyncio.run(db_sync.sync_all_databases(trigger_remote_build=True))

    assert results == {"seerapi": False}
    assert synced == []


def test_sync_database_handles_connect_error(monkeypatch: MonkeyPatch) -> None:
    class FailingStream:
        async def __aenter__(self) -> object:
            raise httpx.ConnectError(CONNECT_ERROR_MESSAGE)

        async def __aexit__(self, *args: object) -> None:
            return None

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        def stream(self, *_args: object, **_kwargs: object) -> FailingStream:
            return FailingStream()

    monkeypatch.setattr(db_sync.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(
        db_sync,
        "_registered_syncs",
        {
            "network_fail": db_sync._SyncEntry(
                "https://example.invalid/data.sqlite",
                60,
                None,
                None,
            )
        },
    )

    result = asyncio.run(db_sync.sync_database("network_fail"))

    assert result is False


def test_sync_database_skips_download_when_local_matches_remote(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "data.sqlite"
    con = sqlite3.connect(db_path)
    con.execute("create table sample (id integer primary key)")
    con.execute("insert into sample (id) values (1)")
    con.commit()
    con.close()
    fingerprint = hashlib.sha256(db_path.read_bytes()).hexdigest()
    streamed: list[bool] = []
    loaded: list[tuple[str, str]] = []

    async def fake_fingerprint(_client: object) -> str:
        return f"{fingerprint}  data.sqlite\n"

    class FakeHeadResponse:
        def __init__(self) -> None:
            self.headers = {"last-modified": "Mon, 22 Jun 2026 12:00:00 GMT"}

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def head(self, *_args: object, **_kwargs: object) -> FakeHeadResponse:
            return FakeHeadResponse()

        def stream(self, *_args: object, **_kwargs: object) -> object:
            streamed.append(True)
            msg = "matching fingerprint should skip download stream"
            raise AssertionError(msg)

    def fake_load_from_file(name: str, file_path: str) -> None:
        loaded.append((name, file_path))

    monkeypatch.setattr(db_sync.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(db_sync.db_manager, "load_from_file", fake_load_from_file)
    monkeypatch.setattr(db_sync, "_last_sync_statuses", {})
    monkeypatch.setattr(db_sync, "_fingerprints", {})
    monkeypatch.setattr(
        db_sync,
        "_registered_syncs",
        {
            "same": db_sync._SyncEntry(
                "https://example.invalid/data.sqlite",
                60,
                fake_fingerprint,
                str(db_path),
            )
        },
    )

    result = asyncio.run(db_sync.sync_database("same"))

    assert result is True
    assert streamed == []
    assert loaded == [("same", str(db_path))]
    status = db_sync._last_sync_statuses["same"]
    assert status.ok is True
    assert status.skipped is True
    assert status.local_before.fingerprint == fingerprint
    assert status.remote.fingerprint == fingerprint
