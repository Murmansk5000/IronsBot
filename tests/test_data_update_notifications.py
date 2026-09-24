import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.core.time import TZ_CN
from ironsbot.integrations.db_registry import DatabaseManager
from ironsbot.integrations.db_sync import runner
from ironsbot.integrations.db_sync.runner import DatabaseSync
from ironsbot.services.operations.data_update import DataUpdate, DataVersion
from ironsbot.services.operations.startup import StartupNoticeService
from tests.test_db_sync_runtime import _DownloadClient, _source


@pytest.mark.parametrize("source", ["seerapi", "aliases"])
@pytest.mark.asyncio
async def test_only_changed_persisted_seerapi_notifies_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    incoming = tmp_path / "incoming.sqlite"
    with sqlite3.connect(incoming) as conn:
        conn.execute("CREATE TABLE sample(id INTEGER)")
    _DownloadClient.content = incoming.read_bytes()
    monkeypatch.setattr(runner.httpx, "AsyncClient", _DownloadClient)
    target = tmp_path / "local.sqlite"
    databases = DatabaseManager()
    events: list[DataUpdate] = []

    async def updated(event: DataUpdate) -> None:
        assert target.read_bytes() == _DownloadClient.content
        assert databases.get_engine(source) is not None
        events.append(event)

    sync = DatabaseSync(databases, on_updated=updated)
    sync.register(source, _source(local_path=str(target)))
    assert all(
        await asyncio.gather(sync.sync_database(source), sync.sync_database(source))
    )
    assert len(events) == (1 if source == "seerapi" else 0)
    databases.close()


@pytest.mark.asyncio
async def test_fingerprint_mismatch_neither_loads_nor_notifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incoming = tmp_path / "incoming.sqlite"
    with sqlite3.connect(incoming) as conn:
        conn.execute("CREATE TABLE sample(id INTEGER)")
    _DownloadClient.content = incoming.read_bytes()
    monkeypatch.setattr(runner.httpx, "AsyncClient", _DownloadClient)
    target = tmp_path / "local.sqlite"
    databases = DatabaseManager()
    loaded = []
    monkeypatch.setattr(databases, "load_from_file", lambda *args: loaded.append(args))
    notice = AsyncMock()
    sync = DatabaseSync(databases, on_updated=notice)
    sync.register("seerapi", _source(local_path=str(target)))
    sync.registered_syncs["seerapi"] = sync.registered_syncs["seerapi"]._replace(
        get_fingerprint=AsyncMock(return_value="0" * 64)
    )
    assert not await sync.sync_database("seerapi")
    assert not loaded
    assert not target.exists()
    notice.assert_not_awaited()


@pytest.mark.parametrize("failure", ["load", "save", "notify"])
@pytest.mark.asyncio
async def test_failures_do_not_report_false_success_or_revert_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    incoming = tmp_path / "incoming.sqlite"
    with sqlite3.connect(incoming) as conn:
        conn.execute("CREATE TABLE sample(id INTEGER)")
    _DownloadClient.content = incoming.read_bytes()
    monkeypatch.setattr(runner.httpx, "AsyncClient", _DownloadClient)
    databases = DatabaseManager()
    notification = AsyncMock(
        side_effect=RuntimeError("notify") if failure == "notify" else None
    )
    sync = DatabaseSync(databases, on_updated=notification)
    sync.register("seerapi", _source(local_path=str(tmp_path / "local.sqlite")))
    if failure == "load":

        def reject(*_args: object) -> None:
            message = "invalid publication"
            raise ValueError(message)

        monkeypatch.setattr(databases, "load_from_file", reject)
    if failure == "save":
        monkeypatch.setattr(
            DatabaseSync, "_save_local_cache", AsyncMock(return_value=(False, None))
        )
    assert await sync.sync_database("seerapi") is (failure == "notify")
    assert notification.await_count == (1 if failure == "notify" else 0)
    if failure == "notify":
        assert await sync.sync_database("seerapi")
        assert notification.await_count == 1
    databases.close()


@pytest.mark.asyncio
async def test_pending_event_is_independent_of_startup_switch_and_bot_count() -> None:
    send = AsyncMock()
    service = StartupNoticeService(cast("Any", SimpleNamespace(send=send)))
    await service.publish("seerapi_data_updated", "updated", "updated once")
    send.assert_not_awaited()
    await asyncio.gather(service.flush_pending(), service.flush_pending())
    send.assert_awaited_once()
    assert not service.parts
    await service.publish("seerapi_data_updated", "updated", "next version")
    assert send.await_count == 2  # noqa: PLR2004


def test_update_message_has_beijing_time_and_only_changed_season() -> None:
    period = (
        datetime(2026, 10, 16, 10, tzinfo=TZ_CN),
        datetime(2027, 1, 8, 10, tzinfo=TZ_CN),
    )
    current = DataVersion("v2", period)
    event = DataUpdate("seerapi", DataVersion("v1"), current, period[0])
    assert "v1 → v2" in event.message()
    assert "20261016" in event.message()
    assert "2026-10-16 10:00:00" in event.message()
    assert (
        "巅峰赛季" not in DataUpdate("seerapi", current, current, period[0]).message()
    )
