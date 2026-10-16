from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from ironsbot.core.time import TZ_CN
from ironsbot.integrations.db_registry import DatabaseManager
from ironsbot.integrations.db_sync import runner
from ironsbot.integrations.db_sync.runner import DatabaseSync
from ironsbot.integrations.seer_data.database import SeerDatabase
from ironsbot.integrations.seer_data.release_contract import SeerApiReleaseContractError
from ironsbot.services.operations.data_update import DataVersion
from tests.test_db_sync_runtime import _DownloadClient, _source
from tests.test_seer_database_version import _create_release

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("registered", [False, True])
def test_unloaded_description_does_not_query_missing_business_tables(
    *,
    registered: bool,
) -> None:
    databases = DatabaseManager()
    if registered:
        databases.register("seerapi")
    data = SeerDatabase(databases, merge_connected_mintmarks=True)
    engine = databases.get_engine("seerapi")
    queries: list[str] = []
    if engine is not None:
        event.listen(
            engine,
            "before_cursor_execute",
            lambda _c, _u, statement, *_args: queries.append(statement),
        )
    try:
        assert data.update_description() == DataVersion("unknown")
        assert not any(
            "api_metadata" in query or "peak_season" in query for query in queries
        )
    finally:
        databases.close()


def test_description_keeps_one_generation_during_reload(tmp_path: Path) -> None:
    first, second = tmp_path / "first.sqlite", tmp_path / "second.sqlite"
    engine_a, generated = _create_release(first, ())
    engine_b, _ = _create_release(second, ())
    later = generated + timedelta(days=1)
    with engine_a.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO peak_season(id,start_time,end_time) VALUES "
                "(1, '2026-10-16 02:00:00', '2027-01-08 02:00:00')"
            )
        )
    with engine_b.begin() as connection:
        connection.execute(
            text("UPDATE api_metadata SET generate_time=:value"),
            {"value": later.replace(tzinfo=None).isoformat(sep=" ")},
        )
        connection.execute(
            text(
                "UPDATE seerapi_metadata SET value='assets-v2' "
                "WHERE key='render_asset_manifest_revision'"
            )
        )
        connection.execute(
            text(
                "INSERT INTO peak_season(id,start_time,end_time) VALUES "
                "(1, '2027-01-08 02:00:00', '2027-04-09 02:00:00')"
            )
        )
    databases = DatabaseManager()
    data = SeerDatabase(databases, merge_connected_mintmarks=True)
    databases.load_from_file("seerapi", str(first))
    baseline = data.update_description()
    current = databases.get_engine("seerapi")
    assert current is not None
    switched = False

    def reload_during_read(
        _conn: Any, _cursor: Any, statement: str, *_args: Any
    ) -> None:
        nonlocal switched
        if not switched and "FROM api_metadata" in statement:
            switched = True
            databases.load_from_file("seerapi", str(second))

    event.listen(current, "before_cursor_execute", reload_during_read)
    try:
        observed = data.update_description()
        assert switched and observed == baseline
        updated = data.update_description()
        assert updated.version.endswith(":assets-v2")
        assert updated.generated_at == later.astimezone(TZ_CN)
        assert updated.season is not None
        assert tuple(value.isoformat() for value in updated.season) == (
            "2027-01-08T10:00:00+08:00",
            "2027-04-09T10:00:00+08:00",
        )
        assert baseline.season is not None
        assert baseline.season[0].isoformat() == "2026-10-16T10:00:00+08:00"
        assert baseline.generated_at == generated.astimezone(TZ_CN)
    finally:
        databases.close()
        engine_a.dispose()
        engine_b.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("cached", [False, True])
async def test_first_sync_description_is_quiet_before_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    *,
    cached: bool,
) -> None:
    incoming = tmp_path / "incoming.sqlite"
    engine, _ = _create_release(incoming, ())
    engine.dispose()
    target = tmp_path / "cache.sqlite"
    if cached:
        target.write_bytes(incoming.read_bytes())
    monkeypatch.setattr(_DownloadClient, "content", incoming.read_bytes())
    monkeypatch.setattr(runner.httpx, "AsyncClient", _DownloadClient)
    databases = DatabaseManager()
    notice = AsyncMock()
    data = SeerDatabase(databases, merge_connected_mintmarks=True)
    sync = DatabaseSync(
        databases,
        describe_database=lambda _name: data.update_description(),
        on_updated=notice,
    )
    sync.register("seerapi", _source(local_path=str(target)))
    if cached:
        from hashlib import sha256

        sync.registered_syncs["seerapi"] = sync.registered_syncs["seerapi"]._replace(
            get_fingerprint=AsyncMock(
                return_value=sha256(incoming.read_bytes()).hexdigest()
            )
        )
    try:
        sync.prepare_all()
        with caplog.at_level(logging.WARNING):
            assert await sync.sync_database("seerapi")
        assert "Data version description unavailable" not in caplog.text
        assert "no such table" not in caplog.text
        assert data.update_description().version != "unknown"
        notice.assert_not_awaited()
    finally:
        databases.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("broken", [False, True])
async def test_loaded_update_reports_matching_versions_and_rejects_bad_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, broken: bool
) -> None:
    first, second = tmp_path / "baseline.sqlite", tmp_path / "incoming.sqlite"
    engine_a, generated = _create_release(first, ())
    engine_b, _ = _create_release(second, ())
    later = generated + timedelta(days=2)
    with engine_a.begin() as connection:
        connection.execute(
            text("UPDATE api_metadata SET data_version='20261120120000'")
        )
    with engine_b.begin() as connection:
        if broken:
            connection.execute(text("DROP TABLE api_metadata"))
        else:
            connection.execute(
                text(
                    "UPDATE api_metadata SET generate_time=:value, "
                    "data_version='20261121120000'"
                ),
                {"value": later.replace(tzinfo=None).isoformat(sep=" ")},
            )
    engine_a.dispose()
    engine_b.dispose()
    target = tmp_path / "persisted.sqlite"
    target.write_bytes(first.read_bytes())
    monkeypatch.setattr(_DownloadClient, "content", second.read_bytes())
    monkeypatch.setattr(runner.httpx, "AsyncClient", _DownloadClient)
    databases = DatabaseManager()
    data = SeerDatabase(databases, merge_connected_mintmarks=True)
    notice = AsyncMock()
    sync = DatabaseSync(
        databases,
        describe_database=lambda _name: data.update_description(),
        on_updated=notice,
    )
    sync.register("seerapi", _source(local_path=str(target)))
    sync.prepare_all()
    databases.load_from_file("seerapi", str(first))
    before = data.update_description()
    try:
        assert await sync.sync_database("seerapi") is not broken
        if broken:
            assert data.update_description() == before
            assert target.read_bytes() == first.read_bytes()
            notice.assert_not_awaited()
        else:
            notice.assert_awaited_once()
            observed = notice.await_args
            assert observed is not None
            update = observed.args[0]
            assert update.before == before
            assert update.after == data.update_description()
            assert update.after.generated_at == later.astimezone(TZ_CN)
            assert target.read_bytes() == second.read_bytes()
            assert await sync.sync_database("seerapi")
            notice.assert_awaited_once()
    finally:
        databases.close()


def test_broken_release_is_not_treated_as_unloaded(tmp_path: Path) -> None:
    source = tmp_path / "broken.sqlite"
    engine, _ = _create_release(source, ())
    databases = DatabaseManager()
    data = SeerDatabase(databases, merge_connected_mintmarks=True)
    try:
        databases.load_from_file("seerapi", str(source))
        baseline = data.update_description()
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE api_metadata"))
        with pytest.raises(SeerApiReleaseContractError, match="api_metadata"):
            databases.load_from_file("seerapi", str(source))
        assert data.update_description() == baseline
        current = databases.get_engine("seerapi")
        assert current is not None
        with current.begin() as connection:
            connection.execute(text("DROP TABLE api_metadata"))
        with pytest.raises(OperationalError):
            data.update_description()
    finally:
        databases.close()
        engine.dispose()
