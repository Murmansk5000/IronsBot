# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from httpx import AsyncClient, MockTransport, Request, Response
from seerapi_models import ApiMetadataORM
from sqlalchemy import event, text
from sqlmodel import Session, SQLModel, create_engine

from ironsbot.app.rendering_composition import SeerRenderSessions
from ironsbot.integrations.db_registry import DatabaseManager
from ironsbot.integrations.http.clients import HttpClients
from ironsbot.integrations.http.seer_images import HttpSeerImageSource
from ironsbot.integrations.seer_data.database import SeerDatabase
from ironsbot.integrations.seer_data.release_contract import SeerApiReleaseContractError
from ironsbot.integrations.storage.render_cache import FileRenderCache
from ironsbot.integrations.storage.render_cache_version import RenderCacheVersion
from ironsbot.integrations.storage.seer_assets import (
    SeerAssetStore,
    SeerAssetStoreLimits,
)
from ironsbot.services.seer.data import DataUnavailableError

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.engine import Engine


def _create_release(source: Path, scopes: tuple[str, ...]) -> tuple[Engine, datetime]:
    engine = create_engine(f"sqlite:///{source}")
    SQLModel.metadata.create_all(engine)
    generated_at = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    with Session(engine) as session:
        session.execute(
            text(
                "CREATE TABLE ironsbot_metadata "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
        )
        session.execute(
            text(
                "INSERT INTO ironsbot_metadata (key, value) VALUES "
                "('ironsbot_schema_contract_version', '1'), "
                "('render_asset_manifest_revision', 'assets-v1'), "
                "('render_asset_manifest_contract_version', '2'), "
                "('render_asset_manifest_complete_scopes', :scopes), "
                "('render_asset_manifest_asset_repository', "
                "'Murmansk-Seer/seer-unity-assets'), "
                "('render_asset_manifest_asset_repository_revision', "
                "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')"
            ),
            {"scopes": json.dumps(scopes)},
        )
        session.add(
            ApiMetadataORM(
                id=1,
                api_url="https://example.invalid/api",
                api_version="1",
                generator_name="test",
                generator_version="1",
                generate_time=generated_at,
            )
        )
        session.commit()

    return engine, generated_at


@pytest.mark.parametrize(
    ("scopes", "expected_categories"),
    [
        (("pet_info",), {"pet_info"}),
        (("type_matchup",), {"type_matchup"}),
        (
            ("peak_pool",),
            {"peak_pool", "peak_pool_vote", "peak_pet_rank", "player_lineup"},
        ),
        (
            ("type_matchup", "peak_pool"),
            {
                "type_matchup",
                "peak_pool",
                "peak_pool_vote",
                "peak_pet_rank",
                "player_lineup",
            },
        ),
        (("new_content_standard",), {"new_content"}),
        ((), set()),
    ],
)
def test_seer_database_version_updates_only_when_database_is_loaded(
    tmp_path: Path,
    scopes: tuple[str, ...],
    expected_categories: set[str],
) -> None:
    source = tmp_path / "seerapi.sqlite"
    engine, generated_at = _create_release(source, scopes)

    databases = DatabaseManager()
    observations: list[tuple[str, str | None]] = []

    def observe_publication() -> None:
        assets = data.render_asset_snapshot()
        observations.append(
            (data.version(), assets.manifest_revision if assets else None)
        )

    # Register before the data adapter: no listener ordering may expose an old
    # manifest after the new engine becomes visible.
    databases.add_load_listener("seerapi", observe_publication)
    data = SeerDatabase(databases, merge_connected_mintmarks=True)

    assert data.version() == "unknown"

    databases.load_from_file("seerapi", str(source))

    expected_version = f"{generated_at.replace(tzinfo=None).isoformat()}:assets-v1"
    assert data.version() == expected_version
    assert observations == [(expected_version, "assets-v1")]
    categories = {
        "pet_info",
        "player_lineup",
        "type_matchup",
        "peak_pool",
        "peak_pool_vote",
        "peak_pet_rank",
        "new_content",
        "lucky_skin_window_v1",
        "preview",
        "unknown",
    }
    assert {
        category for category in categories if data.render_category_available(category)
    } == expected_categories
    snapshot = data.render_asset_snapshot()
    assert snapshot is not None
    assert snapshot.cache_identity == (
        "Murmansk-Seer/seer-unity-assets@"
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:assets-v1"
    )

    databases.close()
    engine.dispose()


def test_publication_lifetime_and_cached_reads(tmp_path: Path) -> None:
    source = tmp_path / "seerapi.sqlite"
    scopes = ("pet_info",)
    engine, generated_at = _create_release(source, scopes)
    databases = DatabaseManager()
    data = SeerDatabase(databases, merge_connected_mintmarks=True)
    observations: list[tuple[str, str | None]] = []

    def observe_publication() -> None:
        assets = data.render_asset_snapshot()
        observations.append(
            (data.version(), assets.manifest_revision if assets else None)
        )

    databases.add_load_listener("seerapi", observe_publication)
    databases.load_from_file("seerapi", str(source))
    expected_version = f"{generated_at.replace(tzinfo=None).isoformat()}:assets-v1"
    snapshot = data.render_asset_snapshot()
    assert snapshot is not None

    late = SeerDatabase(databases, merge_connected_mintmarks=True)
    assert late.version() == expected_version
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ironsbot_metadata SET value='invalid' "
                "WHERE key='ironsbot_schema_contract_version'"
            )
        )
    with pytest.raises(SeerApiReleaseContractError):
        databases.load_from_file("seerapi", str(source))
    assert data.version() == expected_version
    assert data.render_asset_snapshot() is snapshot
    assert observations == [(expected_version, "assets-v1")]

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ironsbot_metadata SET value='1' "
                "WHERE key='ironsbot_schema_contract_version'"
            )
        )
        connection.execute(
            text(
                "UPDATE ironsbot_metadata SET value='assets-v2' "
                "WHERE key='render_asset_manifest_revision'"
            )
        )
    databases.load_from_file("seerapi", str(source))
    updated_version = f"{generated_at.replace(tzinfo=None).isoformat()}:assets-v2"
    assert observations[-1] == (updated_version, "assets-v2")
    assert data.version() == late.version() == updated_version
    assert snapshot.manifest_revision == "assets-v1"

    databases.register("seerapi")
    assert data.version() == "unknown"
    assert data.render_asset_snapshot() is None
    assert not data.render_category_available("pet_info")
    databases.close()
    assert data.version() == late.version() == "unknown"
    assert data.render_asset_snapshot() is None
    engine.dispose()


def test_late_publication_cached_reads_do_not_execute_sql(tmp_path: Path) -> None:
    source = tmp_path / "seerapi.sqlite"
    engine, generated_at = _create_release(source, ("pet_info",))
    databases = DatabaseManager()
    databases.load_from_file("seerapi", str(source))
    data = SeerDatabase(databases, merge_connected_mintmarks=True)
    active = databases.get_engine("seerapi")
    assert active is not None
    executed = Mock()
    event.listen(active, "before_cursor_execute", executed)
    try:
        assert data.version() == (
            f"{generated_at.replace(tzinfo=None).isoformat()}:assets-v1"
        )
        assert data.render_asset_snapshot() is not None
        assert data.render_category_available("pet_info")
        assert not data.render_category_available("type_matchup")
        executed.assert_not_called()
    finally:
        event.remove(active, "before_cursor_execute", executed)
        databases.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_read_snapshot_keeps_publication_and_data_across_await(
    tmp_path: Path,
) -> None:
    source = tmp_path / "seerapi.sqlite"
    engine, _ = _create_release(source, ("pet_info",))
    databases = DatabaseManager()
    data = SeerDatabase(databases, merge_connected_mintmarks=True)
    databases.load_from_file("seerapi", str(source))

    def read_manifest(session: Session) -> str:
        return str(
            session.execute(
                text(
                    "SELECT value FROM ironsbot_metadata "
                    "WHERE key='render_asset_manifest_revision'"
                )
            ).scalar_one()
        )

    try:
        with data.read_snapshot() as old:
            publication = old.publication
            assert publication.assets is not None
            assert publication.assets.manifest_revision == "assets-v1"
            assert publication.category_available("pet_info")
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE ironsbot_metadata SET value='assets-v2' "
                        "WHERE key='render_asset_manifest_revision'"
                    )
                )
            await asyncio.to_thread(databases.load_from_file, "seerapi", str(source))
            with old.query(read_manifest) as value:
                assert value == publication.assets.manifest_revision
            with data.read_snapshot() as fresh, fresh.query(read_manifest) as value:
                assert fresh.publication.assets is not None
                assert (
                    value == fresh.publication.assets.manifest_revision == "assets-v2"
                )
            with data.query(read_manifest) as value:
                assert value == "assets-v2"
            databases.close()
            with old.query(read_manifest) as value:
                assert value == "assets-v1"
        with (
            pytest.raises(DataUnavailableError, match="snapshot is closed"),
            old.query(read_manifest),
        ):
            pytest.fail("closed snapshots must not reopen retired engines")
        with pytest.raises(DataUnavailableError), data.read_snapshot():
            pytest.fail("missing engines must not create a read snapshot")
    finally:
        databases.close()
        engine.dispose()


def test_seer_database_rejects_release_without_schema_contract(
    tmp_path: Path,
) -> None:
    source = tmp_path / "seerapi.sqlite"
    engine = create_engine(f"sqlite:///{source}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.execute(
            text(
                "CREATE TABLE ironsbot_metadata "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
        )
        session.add(
            ApiMetadataORM(
                id=1,
                api_url="https://example.invalid/api",
                api_version="1",
                generator_name="test",
                generator_version="1",
                generate_time=datetime(2026, 8, 13, tzinfo=timezone.utc),
            )
        )
        session.commit()

    databases = DatabaseManager()
    data = SeerDatabase(databases, merge_connected_mintmarks=True)
    with pytest.raises(SeerApiReleaseContractError, match="schema 契约版本不兼容"):
        databases.load_from_file("seerapi", str(source))

    assert data.version() == "unknown"
    assert data.render_asset_snapshot() is None


def _update_asset_release(engine: Engine, revision: str, manifest: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ironsbot_metadata SET value=:value WHERE key=:key"),
            [
                {
                    "key": "render_asset_manifest_asset_repository_revision",
                    "value": revision,
                },
                {"key": "render_asset_manifest_revision", "value": manifest},
            ],
        )


@pytest.mark.asyncio
async def test_render_inputs_stay_bound_across_publication_and_rollback(
    tmp_path: Path,
) -> None:
    source = tmp_path / "seerapi.sqlite"
    engine, _ = _create_release(source, ("pet_info",))
    databases = DatabaseManager()
    data = SeerDatabase(databases, merge_connected_mintmarks=True)
    databases.load_from_file("seerapi", str(source))
    requests: list[str] = []

    def respond(request: Request) -> Response:
        requests.append(str(request.url))
        return Response(200, content=b"old" if "a" * 40 in request.url.path else b"new")

    async with AsyncClient(transport=MockTransport(respond)) as client:
        clients = HttpClients(cache=client, origin=client)
        assets = SeerAssetStore(
            HttpSeerImageSource(
                clients, asset_snapshot_getter=data.render_asset_snapshot
            ),
            tmp_path / "assets",
            SeerAssetStoreLimits(1024, 1024 * 1024, 1, 30),
        )
        versions = RenderCacheVersion(data.version, ())
        cache = FileRenderCache(tmp_path / "renders", 1024, version_getter=versions)
        sessions = SeerRenderSessions(data, clients, assets, cache, versions)
        try:
            await _check_bound_render_inputs(sessions, engine, databases, source)
            before = len(requests)
            with sessions.open() as restored:
                assert restored.cache.entry("pet_info", "1").get() == b"old-render"
                assert (
                    await restored.images.fetch("pet_body", "1", fallback=False)
                    == b"old"
                )
            assert len(requests) == before
            assert any("b" * 40 in url for url in requests)
        finally:
            databases.close()
            engine.dispose()


async def _check_bound_render_inputs(
    sessions: SeerRenderSessions,
    engine: Engine,
    databases: DatabaseManager,
    source: Path,
) -> None:
    with sessions.open() as old:
        old_entry = old.cache.entry("pet_info", "1")
        assert old_entry.get() is None
        assert await old.images.fetch("pet_body", "1", fallback=False) == b"old"
        _update_asset_release(engine, "b" * 40, "assets-v2")
        await asyncio.to_thread(databases.load_from_file, "seerapi", str(source))
        with sessions.open() as fresh:
            fresh_entry = fresh.cache.entry("pet_info", "1")
            assert fresh_entry.get() is None
            assert await fresh.images.fetch("pet_body", "1", fallback=False) == b"new"
            assert await old.images.fetch("pet_body", "2", fallback=False) == b"old"
            fresh_entry.put(b"new-render")
            old_entry.put(b"old-render")
            assert fresh_entry.get() == b"new-render"
        assert old_entry.get() == b"old-render"
    _update_asset_release(engine, "a" * 40, "assets-v1")
    await asyncio.to_thread(databases.load_from_file, "seerapi", str(source))
