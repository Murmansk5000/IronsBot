import asyncio
import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import httpx
from pytest import MonkeyPatch
from typing_extensions import Self

from ironsbot.config.models.operations import (
    DataSourceConfig,
    DataSyncConfig,
    RemoteBuildConfig,
    RemoteBuildStepConfig,
)
from ironsbot.integrations.db_registry import DatabaseManager
from ironsbot.integrations.db_sync import runner as db_sync_runner
from ironsbot.integrations.db_sync.github_actions import WorkflowRunResult
from ironsbot.integrations.db_sync.runner import DatabaseSync
from ironsbot.runtime.cache_paths import CachePaths
from ironsbot.services.operations.data_sync import DataSyncService

CONNECT_ERROR_MESSAGE = "connection failed"


@dataclass
class FakeJob:
    id: str


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []

    def add_job(
        self,
        func: Any,
        trigger: str,
        **kwargs: Any,
    ) -> FakeJob:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})
        return FakeJob(str(kwargs["id"]))

    def get_jobs(self) -> list[FakeJob]:
        return [FakeJob(str(job["id"])) for job in self.jobs]

    def remove_job(self, job_id: str) -> None:
        self.jobs = [job for job in self.jobs if job["id"] != job_id]


class _DownloadHeadResponse:
    def __init__(self) -> None:
        self.headers = {"last-modified": "Mon, 22 Jun 2026 12:00:00 GMT"}

    def raise_for_status(self) -> None:
        return None


class _DownloadStream:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    async def aiter_bytes(self, *, chunk_size: int) -> Any:
        del chunk_size
        yield _DownloadClient.content


class _DownloadClient:
    content: ClassVar[bytes] = b""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def head(self, *_args: object, **_kwargs: object) -> _DownloadHeadResponse:
        return _DownloadHeadResponse()

    def stream(self, *_args: object, **_kwargs: object) -> _DownloadStream:
        return _DownloadStream()


def _source(
    *,
    local_path: str = "",
    fingerprint_url: str = "",
    remote_build: RemoteBuildConfig | None = None,
) -> DataSourceConfig:
    return DataSourceConfig(
        url="https://example.invalid/data.sqlite",
        fingerprint_url=fingerprint_url,
        interval_minutes=15,
        local_path=local_path,
        remote_build=remote_build or RemoteBuildConfig(),
    )


def _config(
    *,
    github_token: str = "",
    on_startup: bool = True,
    startup_trigger_remote_build: bool = False,
    interval_enabled: bool = True,
) -> DataSyncConfig:
    return DataSyncConfig(
        github_token=github_token,
        on_startup=on_startup,
        startup_trigger_remote_build=startup_trigger_remote_build,
        interval_enabled=interval_enabled,
        sources={},
    )


def _remote_build_config() -> RemoteBuildConfig:
    return RemoteBuildConfig(
        enabled=True,
        repository="Murmansk-Seer/seerapi",
        workflow_id="build-seerapi-data-db.yml",
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
                workflow_id="build-seerapi-data-db.yml",
            ),
        ],
    )


def test_registration_defers_database_engine_creation() -> None:
    databases = DatabaseManager()
    sync = DatabaseSync(databases)

    sync.register("unit", _source())

    assert sync.remote_names() == ("unit",)
    assert databases.get_engine("unit") is None


def test_manual_sync_shows_current_local_data_versions(tmp_path: Path) -> None:
    cache_path = tmp_path / "seerapi.sqlite"
    cache_path.write_bytes(b"seerapi cache")
    sync = DatabaseSync(DatabaseManager())
    sync.register(
        "seerapi",
        _source(
            local_path=str(cache_path),
            remote_build=_remote_build_config(),
        ),
    )
    sync.register("aliases", _source(local_path=str(tmp_path / "aliases.sqlite")))
    sync.fingerprints["seerapi"] = "0123456789abcdef"
    service = DataSyncService(_config(), sync)

    message, should_run = service.prepare_manual(force=False)

    assert should_run
    assert (
        "开始检查远程数据更新：seerapi；"
        "随后更新数据：seerapi, aliases，请稍等。"
    ) in message
    assert "当前本地数据版本：" in message
    assert "seerapi：" in message
    assert "sha256=0123456789ab" in message
    assert "aliases：未安装" in message


def test_startup_prepares_database_and_interval_job() -> None:
    databases = DatabaseManager()
    sync = DatabaseSync(databases)
    sync.register("unit", _source())
    scheduler = FakeScheduler()
    service = DataSyncService(
        _config(interval_enabled=True, on_startup=False),
        sync,
    )

    try:
        assert asyncio.run(service.startup(scheduler)) is None
        assert databases.get_engine("unit") is not None
        assert scheduler.jobs == [
            {
                "func": sync.run_sync_database,
                "trigger": "interval",
                "args": ["unit"],
                "minutes": 15,
                "id": "db_sync_unit",
                "replace_existing": True,
            }
        ]
    finally:
        databases.close()


def test_startup_sync_triggers_build_and_loads_failed_cache(
    monkeypatch: MonkeyPatch,
) -> None:
    databases = DatabaseManager()
    sync = DatabaseSync(databases)
    sync.register("unit", _source())
    calls: list[tuple[str, bool]] = []

    async def run_all(
        _self: DatabaseSync,
        *,
        github_token: str,
        trigger_remote_build: bool = False,
        force_remote_build: bool = False,
    ) -> tuple[bool, dict[str, bool]]:
        assert not force_remote_build
        calls.append((github_token, trigger_remote_build))
        return True, {"unit": False}

    def load_failed(_self: DatabaseSync, results: dict[str, bool]) -> None:
        calls.append(("load_failed", results["unit"]))

    monkeypatch.setattr(DatabaseSync, "run_sync_all_databases", run_all)
    monkeypatch.setattr(DatabaseSync, "load_failed_cached", load_failed)
    service = DataSyncService(
        _config(
            github_token="token",
            on_startup=True,
            interval_enabled=False,
            startup_trigger_remote_build=True,
        ),
        sync,
    )

    try:
        notice = asyncio.run(service.startup(FakeScheduler()))
    finally:
        databases.close()

    assert calls == [("token", True), ("load_failed", False)]
    assert notice is not None
    assert "unit" in notice


def test_manual_sync_runs_remote_build_pipeline_before_download(
    monkeypatch: MonkeyPatch,
) -> None:
    sync = DatabaseSync(DatabaseManager())
    sync.register("seerapi", _source(remote_build=_remote_build_pipeline_config()))
    calls: list[str] = []

    async def build(
        step: RemoteBuildStepConfig,
        *,
        token: str,
    ) -> WorkflowRunResult:
        calls.append(f"build:{step.name}:{token}")
        return WorkflowRunResult(
            ok=True,
            status="completed",
            conclusion="success",
            html_url=f"https://github.com/{step.repository}/actions/runs/1",
            message="ok",
        )

    async def download(_self: DatabaseSync, name: str) -> bool:
        calls.append(f"sync:{name}")
        return True

    monkeypatch.setattr(db_sync_runner, "trigger_and_wait_workflow", build)
    monkeypatch.setattr(DatabaseSync, "sync_database", download)

    did_run, results = asyncio.run(
        sync.run_sync_all_databases(
            github_token="token",
            trigger_remote_build=True,
        )
    )

    assert did_run
    assert results == {"seerapi": True}
    assert calls == [
        "build:refresh_official_sources:token",
        "build:refresh_unity_config:token",
        "build:sync_config_sources:token",
        "build:build_api_data:token",
        "build:build_ironsbot_data:token",
        "sync:seerapi",
    ]


def test_force_remote_build_overrides_supported_inputs(
    monkeypatch: MonkeyPatch,
) -> None:
    sync = DatabaseSync(DatabaseManager())
    sync.register("seerapi", _source(remote_build=_remote_build_pipeline_config()))
    inputs_seen: dict[str, dict[str, object]] = {}

    async def build(
        step: RemoteBuildStepConfig,
        *,
        token: str,
    ) -> WorkflowRunResult:
        assert token == "token"
        inputs_seen[step.name] = dict(step.inputs)
        return WorkflowRunResult(
            ok=True,
            status="completed",
            conclusion="success",
            html_url="",
            message="ok",
        )

    async def download(_self: DatabaseSync, _name: str) -> bool:
        return True

    monkeypatch.setattr(db_sync_runner, "trigger_and_wait_workflow", build)
    monkeypatch.setattr(DatabaseSync, "sync_database", download)

    _did_run, results = asyncio.run(
        sync.run_sync_all_databases(
            github_token="token",
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


def test_remote_build_failure_skips_download(monkeypatch: MonkeyPatch) -> None:
    sync = DatabaseSync(DatabaseManager())
    sync.register("seerapi", _source(remote_build=_remote_build_config()))
    downloaded: list[str] = []

    async def failed_build(
        _step: RemoteBuildStepConfig,
        *,
        token: str,
    ) -> WorkflowRunResult:
        assert token == "token"
        return WorkflowRunResult(
            ok=False,
            status="completed",
            conclusion="failure",
            html_url="",
            message="failed",
        )

    async def download(_self: DatabaseSync, name: str) -> bool:
        downloaded.append(name)
        return True

    monkeypatch.setattr(db_sync_runner, "trigger_and_wait_workflow", failed_build)
    monkeypatch.setattr(DatabaseSync, "sync_database", download)

    _did_run, results = asyncio.run(
        sync.run_sync_all_databases(
            github_token="token",
            trigger_remote_build=True,
        )
    )

    assert results == {"seerapi": False}
    assert downloaded == []


def test_remote_build_without_token_fails_before_download(
    monkeypatch: MonkeyPatch,
) -> None:
    sync = DatabaseSync(DatabaseManager())
    sync.register("seerapi", _source(remote_build=_remote_build_config()))

    async def fail_download(_self: DatabaseSync, _name: str) -> bool:
        msg = "download must not run without a build token"
        raise AssertionError(msg)

    monkeypatch.setattr(DatabaseSync, "sync_database", fail_download)

    _did_run, results = asyncio.run(
        sync.run_sync_all_databases(
            github_token="",
            trigger_remote_build=True,
        )
    )

    assert results == {"seerapi": False}


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
    sync = DatabaseSync(DatabaseManager())
    sync.register("network_fail", _source())

    assert asyncio.run(sync.sync_database("network_fail")) is False


def test_sync_database_uses_matching_local_cache(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "data.sqlite"
    with sqlite3.connect(db_path) as connection:
        connection.execute("create table sample (id integer primary key)")
        connection.execute("insert into sample (id) values (1)")
    fingerprint = hashlib.sha256(db_path.read_bytes()).hexdigest()
    loaded: list[tuple[str, str]] = []

    class FakeHeadResponse:
        def __init__(self) -> None:
            self.headers = {
                "last-modified": "Mon, 22 Jun 2026 12:00:00 GMT"
            }

        def raise_for_status(self) -> None:
            return None

    class FakeFingerprintResponse:
        text = f"{fingerprint}  data.sqlite\n"

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def head(self, *_args: object, **_kwargs: object) -> FakeHeadResponse:
            return FakeHeadResponse()

        async def get(
            self,
            *_args: object,
            **_kwargs: object,
        ) -> FakeFingerprintResponse:
            return FakeFingerprintResponse()

        def stream(self, *_args: object, **_kwargs: object) -> object:
            msg = "matching fingerprint must skip download"
            raise AssertionError(msg)

    databases = DatabaseManager()
    monkeypatch.setattr(databases, "load_from_file", lambda *args: loaded.append(args))
    monkeypatch.setattr(db_sync_runner.httpx, "AsyncClient", FakeClient)
    cache_root = tmp_path / "cache"
    sync = DatabaseSync(databases, cache_paths=CachePaths(cache_root))
    source = _source(
        local_path=str(db_path),
        fingerprint_url="https://example.invalid/data.sqlite.sha256",
    )
    sync.register("same", source)

    assert asyncio.run(sync.sync_database("same")) is True
    assert loaded == [("same", str(db_path))]
    assert sync.last_sync_statuses["same"].skipped
    assert not cache_root.exists()


def test_sync_database_uses_disposable_downloads_directory(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.sqlite"
    with sqlite3.connect(source_path) as connection:
        connection.execute("create table sample (id integer primary key)")
    _DownloadClient.content = source_path.read_bytes()
    loaded_paths: list[Path] = []

    databases = DatabaseManager()
    monkeypatch.setattr(
        databases,
        "load_from_file",
        lambda _name, path: loaded_paths.append(Path(path)),
    )
    monkeypatch.setattr(db_sync_runner.httpx, "AsyncClient", _DownloadClient)
    cache_root = tmp_path / "cache"
    sync = DatabaseSync(databases, cache_paths=CachePaths(cache_root))
    sync.register("download", _source())

    assert asyncio.run(sync.sync_database("download"))
    assert loaded_paths[0].parent == cache_root / "downloads"
    assert not list((cache_root / "downloads").glob("*.sqlite"))
