import asyncio
import hashlib
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import httpx
import nonebot
from pytest import MonkeyPatch
from typing_extensions import Self

from ironsbot.config.loader import clear_app_config_cache
from ironsbot.config.models.runtime import (
    DataSyncConfig,
    RemoteBuildConfig,
    RemoteBuildStepConfig,
)
from ironsbot.config.models.secrets import SecretsConfig

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")
clear_app_config_cache()

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

try:
    nonebot.load_plugin("ironsbot.plugins.db_sync")
except RuntimeError as e:
    if "Plugin already exists" not in str(e):
        raise

from ironsbot.integrations.db_sync import registry as db_sync_registry
from ironsbot.integrations.db_sync import runner as db_sync_runner
from ironsbot.integrations.db_sync import state as db_sync_state
from ironsbot.integrations.db_sync.github_actions import WorkflowRunResult
from ironsbot.integrations.db_sync.models import SyncEntry
from ironsbot.plugins.db_sync import runtime as db_sync_runtime

CONNECT_ERROR_MESSAGE = "connection failed"


def _data_sync_config(
    *,
    interval_enabled: bool,
    on_startup: bool,
    startup_trigger_remote_build: bool = False,
) -> DataSyncConfig:
    return DataSyncConfig(
        interval_enabled=interval_enabled,
        on_startup=on_startup,
        startup_trigger_remote_build=startup_trigger_remote_build,
    )


@dataclass(frozen=True, slots=True)
class FakeRuntimeConfig:
    data_sync: DataSyncConfig


@dataclass(frozen=True, slots=True)
class FakeAppConfig:
    runtime: FakeRuntimeConfig


def _app_config(*, data_sync: DataSyncConfig) -> FakeAppConfig:
    return FakeAppConfig(runtime=FakeRuntimeConfig(data_sync=data_sync))


def _secrets_config(*, github_workflow_token: str) -> SecretsConfig:
    return SecretsConfig(github_workflow_token=github_workflow_token)


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


def test_register_database_defers_engine_and_scheduler_setup(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_engines: list[str] = []
    monkeypatch.setattr(db_sync_state, "registered_syncs", {})
    monkeypatch.setattr(db_sync_state, "registered_local_databases", {})
    monkeypatch.setattr(
        db_sync_runner.db_manager,
        "register",
        registered_engines.append,
    )

    db_sync_registry.register_database(
        "unit",
        sync_url="https://example.invalid/unit.sqlite",
        sync_interval_minutes=15,
    )

    assert "unit" in db_sync_state.registered_syncs
    assert registered_engines == []


def test_db_sync_startup_prepares_engines_and_interval_jobs(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_engines: list[str] = []
    scheduler = FakeScheduler()
    monkeypatch.setattr(db_sync_state, "registered_syncs",
        {
            "unit": SyncEntry(
                "https://example.invalid/unit.sqlite",
                15,
                None,
                None,
                None,
            )
        },
    )
    monkeypatch.setattr(db_sync_state, "registered_local_databases", {})
    monkeypatch.setattr(db_sync_state, "prepared_databases", set())
    monkeypatch.setattr(
        db_sync_runner.db_manager,
        "register",
        registered_engines.append,
    )
    monkeypatch.setattr(
        db_sync_runtime,
        "get_app_config",
        lambda: _app_config(
            data_sync=_data_sync_config(interval_enabled=True, on_startup=False)
        ),
    )

    asyncio.run(db_sync_runtime.start_db_sync(scheduler))

    assert registered_engines == ["unit"]
    assert scheduler.jobs == [
        {
            "func": db_sync_runner.run_sync_database,
            "trigger": "interval",
            "args": ["unit"],
            "minutes": 15,
            "id": "db_sync_unit",
            "replace_existing": True,
        }
    ]


def test_db_sync_startup_can_trigger_remote_build(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[bool] = []
    scheduler = FakeScheduler()
    monkeypatch.setattr(db_sync_state, "registered_syncs",
        {
            "unit": SyncEntry(
                "https://example.invalid/unit.sqlite",
                15,
                None,
                None,
                _remote_build_config(),
            )
        },
    )
    monkeypatch.setattr(db_sync_state, "registered_local_databases", {})
    monkeypatch.setattr(db_sync_state, "prepared_databases", set())
    monkeypatch.setattr(db_sync_runner.db_manager, "register", lambda _name: None)
    monkeypatch.setattr(db_sync_runner, "load_cached_database", lambda _name: False)
    monkeypatch.setattr(
        db_sync_runtime,
        "get_app_config",
        lambda: _app_config(
            data_sync=_data_sync_config(
                interval_enabled=False,
                on_startup=True,
                startup_trigger_remote_build=True,
            )
        ),
    )

    async def fake_run_sync_all_databases(
        *,
        trigger_remote_build: bool = False,
    ) -> tuple[bool, dict[str, bool]]:
        calls.append(trigger_remote_build)
        return True, {"unit": True}

    monkeypatch.setattr(
        db_sync_runner,
        "run_sync_all_databases",
        fake_run_sync_all_databases,
    )
    monkeypatch.setattr(db_sync_runner, "format_sync_result_notice",
        lambda results, *, title_prefix: f"{title_prefix}:{results}",
    )

    asyncio.run(db_sync_runtime.start_db_sync(scheduler))

    assert calls == [True]
    assert db_sync_runtime.get_startup_sync_notice() == (
        "启动数据同步:{'unit': True}"
    )


def test_db_sync_startup_falls_back_to_cache_on_sync_failure(
    monkeypatch: MonkeyPatch,
) -> None:
    loaded: list[str] = []
    scheduler = FakeScheduler()
    monkeypatch.setattr(db_sync_state, "registered_syncs",
        {
            "unit": SyncEntry(
                "https://example.invalid/unit.sqlite",
                15,
                None,
                None,
                None,
            )
        },
    )
    monkeypatch.setattr(db_sync_state, "registered_local_databases", {})
    monkeypatch.setattr(db_sync_state, "prepared_databases", set())
    monkeypatch.setattr(db_sync_runner.db_manager, "register", lambda _name: None)
    monkeypatch.setattr(db_sync_runner, "load_cached_database", loaded.append)
    monkeypatch.setattr(
        db_sync_runtime,
        "get_app_config",
        lambda: _app_config(
            data_sync=_data_sync_config(
                interval_enabled=False,
                on_startup=True,
                startup_trigger_remote_build=False,
            )
        ),
    )

    async def fake_run_sync_all_databases(
        *,
        trigger_remote_build: bool = False,
    ) -> tuple[bool, dict[str, bool]]:
        assert not trigger_remote_build
        return True, {"unit": False}

    monkeypatch.setattr(
        db_sync_runner,
        "run_sync_all_databases",
        fake_run_sync_all_databases,
    )
    monkeypatch.setattr(db_sync_runner, "format_sync_result_notice",
        lambda results, *, title_prefix: f"{title_prefix}:{results}",
    )

    asyncio.run(db_sync_runtime.start_db_sync(scheduler))

    assert loaded == ["unit"]
    assert db_sync_runtime.get_startup_sync_notice() == (
        "启动数据同步:{'unit': False}"
    )


def _remote_build_config() -> RemoteBuildConfig:
    return RemoteBuildConfig(
        enabled=True,
        repository="Murmansk-Seer/seerapi",
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
                name="refresh_official_sources",
                repository="Murmansk-Seer/data-update-workflows",
                workflow_id="update.yml",
                inputs={
                    "force-update-assets": False,
                    "force-update-config": False,
                    "dispatch-api-data": False,
                },
            ),
            RemoteBuildStepConfig(
                name="refresh_unity_config",
                repository="Murmansk-Seer/seer-unity-config-parser",
                workflow_id="schedule.yml",
            ),
            RemoteBuildStepConfig(
                name="sync_config_sources",
                repository="Murmansk-Seer/config-sources",
                workflow_id="sync-upstream.yml",
            ),
            RemoteBuildStepConfig(
                name="build_api_data",
                repository="Murmansk-Seer/api-data",
                workflow_id="main.yml",
            ),
            RemoteBuildStepConfig(
                name="build_ironsbot_data",
                repository="Murmansk-Seer/seerapi",
                workflow_id="build-ironsbot-data-db.yml",
            ),
        ],
    )


def test_manual_sync_triggers_remote_build_before_download(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(db_sync_state, "registered_syncs",
        {
            "seerapi": SyncEntry(
                "https://example.invalid/seerapi.sqlite",
                60,
                None,
                None,
                _remote_build_config(),
            ),
            "aliases": SyncEntry(
                "https://example.invalid/aliases.sqlite",
                60,
                None,
                None,
                None,
            ),
        },
    )
    monkeypatch.setattr(db_sync_runner, "load_secrets_config",
        lambda: _secrets_config(github_workflow_token="token"),
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
            html_url="https://github.com/Murmansk-Seer/seerapi/actions/runs/1",
            message="ok",
        )

    async def fake_sync(name: str) -> bool:
        calls.append(f"sync:{name}")
        return True

    monkeypatch.setattr(db_sync_runner, "trigger_and_wait_workflow", fake_build)
    monkeypatch.setattr(db_sync_runner, "sync_database", fake_sync)

    results = asyncio.run(db_sync_runner.sync_all_databases(trigger_remote_build=True))

    assert results == {"seerapi": True, "aliases": True}
    assert calls == [
        "build:Murmansk-Seer/seerapi:token",
        "sync:seerapi",
        "sync:aliases",
    ]


def test_manual_sync_runs_remote_build_pipeline_before_download(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(db_sync_state, "registered_syncs",
        {
            "seerapi": SyncEntry(
                "https://example.invalid/seerapi.sqlite",
                60,
                None,
                None,
                _remote_build_pipeline_config(),
            ),
        },
    )
    monkeypatch.setattr(db_sync_runner, "load_secrets_config",
        lambda: _secrets_config(github_workflow_token="token"),
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

    monkeypatch.setattr(db_sync_runner, "trigger_and_wait_workflow", fake_build)
    monkeypatch.setattr(db_sync_runner, "sync_database", fake_sync)

    results = asyncio.run(db_sync_runner.sync_all_databases(trigger_remote_build=True))

    assert results == {"seerapi": True}
    assert calls == [
        "build:refresh_official_sources:Murmansk-Seer/data-update-workflows:token",
        "build:refresh_unity_config:Murmansk-Seer/seer-unity-config-parser:token",
        "build:sync_config_sources:Murmansk-Seer/config-sources:token",
        "build:build_api_data:Murmansk-Seer/api-data:token",
        "build:build_ironsbot_data:Murmansk-Seer/seerapi:token",
        "sync:seerapi",
    ]


def test_force_remote_build_adds_force_input_to_supported_steps(
    monkeypatch: MonkeyPatch,
) -> None:
    inputs_seen: dict[str, dict[str, object]] = {}
    monkeypatch.setattr(db_sync_state, "registered_syncs",
        {
            "seerapi": SyncEntry(
                "https://example.invalid/seerapi.sqlite",
                60,
                None,
                None,
                _remote_build_pipeline_config(),
            ),
        },
    )
    monkeypatch.setattr(db_sync_runner, "load_secrets_config",
        lambda: _secrets_config(github_workflow_token="token"),
    )

    async def fake_build(
        config: RemoteBuildStepConfig,
        *,
        token: str,
    ) -> WorkflowRunResult:
        assert token == "token"
        inputs_seen[config.name] = dict(config.inputs)
        return WorkflowRunResult(
            ok=True,
            status="completed",
            conclusion="success",
            html_url=f"https://github.com/{config.repository}/actions/runs/1",
            message="ok",
        )

    async def fake_sync(_name: str) -> bool:
        return True

    monkeypatch.setattr(db_sync_runner, "trigger_and_wait_workflow", fake_build)
    monkeypatch.setattr(db_sync_runner, "sync_database", fake_sync)

    results = asyncio.run(
        db_sync_runner.sync_all_databases(
            trigger_remote_build=True,
            force_remote_build=True,
        )
    )

    assert results == {"seerapi": True}
    assert inputs_seen == {
        "refresh_official_sources": {
            "force-update-assets": True,
            "force-update-config": True,
            "dispatch-api-data": False,
        },
        "refresh_unity_config": {},
        "sync_config_sources": {"force": True},
        "build_api_data": {"force": True},
        "build_ironsbot_data": {"force": True},
    }


def test_remote_build_failure_skips_old_release_download(
    monkeypatch: MonkeyPatch,
) -> None:
    synced: list[str] = []
    monkeypatch.setattr(db_sync_state, "registered_syncs",
        {
            "seerapi": SyncEntry(
                "https://example.invalid/seerapi.sqlite",
                60,
                None,
                None,
                _remote_build_config(),
            ),
            "aliases": SyncEntry(
                "https://example.invalid/aliases.sqlite",
                60,
                None,
                None,
                None,
            ),
        },
    )
    monkeypatch.setattr(db_sync_runner, "load_secrets_config",
        lambda: _secrets_config(github_workflow_token="token"),
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
            html_url="https://github.com/Murmansk-Seer/seerapi/actions/runs/1",
            message=f"{config.workflow_id} failed with {token}",
        )

    async def fake_sync(name: str) -> bool:
        synced.append(name)
        return True

    monkeypatch.setattr(db_sync_runner, "trigger_and_wait_workflow", fake_build)
    monkeypatch.setattr(db_sync_runner, "sync_database", fake_sync)

    results = asyncio.run(db_sync_runner.sync_all_databases(trigger_remote_build=True))

    assert results == {"seerapi": False, "aliases": True}
    assert synced == ["aliases"]


def test_scheduled_sync_does_not_trigger_remote_build(
    monkeypatch: MonkeyPatch,
) -> None:
    synced: list[str] = []
    monkeypatch.setattr(db_sync_state, "registered_syncs",
        {
            "seerapi": SyncEntry(
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

    monkeypatch.setattr(db_sync_runner, "trigger_and_wait_workflow", fail_build)
    monkeypatch.setattr(db_sync_runner, "sync_database", fake_sync)

    results = asyncio.run(db_sync_runner.sync_all_databases())

    assert results == {"seerapi": True}
    assert synced == ["seerapi"]


def test_remote_build_enabled_without_token_fails_fast(
    monkeypatch: MonkeyPatch,
) -> None:
    synced: list[str] = []
    monkeypatch.setattr(db_sync_state, "registered_syncs",
        {
            "seerapi": SyncEntry(
                "https://example.invalid/seerapi.sqlite",
                60,
                None,
                None,
                _remote_build_config(),
            )
        },
    )
    monkeypatch.setattr(db_sync_runner, "load_secrets_config",
        lambda: _secrets_config(github_workflow_token=""),
    )

    async def fake_sync(name: str) -> bool:
        synced.append(name)
        return True

    monkeypatch.setattr(db_sync_runner, "sync_database", fake_sync)

    results = asyncio.run(db_sync_runner.sync_all_databases(trigger_remote_build=True))

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

    monkeypatch.setattr(db_sync_runner.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(db_sync_state, "registered_syncs",
        {
            "network_fail": SyncEntry(
                "https://example.invalid/data.sqlite",
                60,
                None,
                None,
            )
        },
    )

    result = asyncio.run(db_sync_runner.sync_database("network_fail"))

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

    monkeypatch.setattr(db_sync_runner.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(
        db_sync_runner.db_manager,
        "load_from_file",
        fake_load_from_file,
    )
    monkeypatch.setattr(db_sync_state, "last_sync_statuses", {})
    monkeypatch.setattr(db_sync_state, "fingerprints", {})
    monkeypatch.setattr(db_sync_state, "registered_syncs",
        {
            "same": SyncEntry(
                "https://example.invalid/data.sqlite",
                60,
                fake_fingerprint,
                str(db_path),
            )
        },
    )

    result = asyncio.run(db_sync_runner.sync_database("same"))

    assert result is True
    assert streamed == []
    assert loaded == [("same", str(db_path))]
    status = db_sync_state.last_sync_statuses["same"]
    assert status.ok is True
    assert status.skipped is True
    assert status.local_before.fingerprint == fingerprint
    assert status.remote.fingerprint == fingerprint
