# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from httpx import AsyncClient, MockTransport, Request, Response
from seerapi_models import ApiMetadataORM
from sqlalchemy import event, text
from sqlmodel import Session, SQLModel, create_engine

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.app.rendering_composition import SeerRenderSessions
from ironsbot.extensions.contracts import PlayerLineupSlot
from ironsbot.integrations.db_registry import DatabaseManager
from ironsbot.integrations.http.clients import HttpClients
from ironsbot.integrations.http.seer_images import HttpSeerImageSource
from ironsbot.integrations.seer_data.database import SeerDatabase
from ironsbot.integrations.seer_data.new_content_repository import (
    PublishedNewContentRepository,
)
from ironsbot.integrations.seer_data.player_lineup_entries import (
    PublishedPlayerLineupEntryResolver,
)
from ironsbot.integrations.seer_data.release_contract import SeerApiReleaseContractError
from ironsbot.integrations.storage.render_cache import FileRenderCache
from ironsbot.integrations.storage.render_cache_version import RenderCacheVersion
from ironsbot.integrations.storage.seer_assets import (
    SeerAssetStore,
    SeerAssetStoreLimits,
)
from ironsbot.services.seer.data import (
    DataPublicationChangedError,
    DataUnavailableError,
)
from ironsbot.services.seer.new_content import (
    NewContentService,
    NewContentSnapshotChangedError,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.engine import Engine

    from ironsbot.services.seer.images import ImageKind


def _create_release(source: Path, scopes: tuple[str, ...]) -> tuple[Engine, datetime]:
    engine = create_engine(f"sqlite:///{source}")
    SQLModel.metadata.create_all(engine)
    generated_at = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    with Session(engine) as session:
        session.execute(
            text(
                "CREATE TABLE peak_cost_pool (id INTEGER PRIMARY KEY, cost INTEGER, "
                "start_time TEXT, end_time TEXT)"
            )
        )
        session.execute(text("ALTER TABLE pet ADD COLUMN peak_cost_pool_id INTEGER"))
        session.execute(
            text(
                "CREATE TABLE ironsbot_metadata "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
        )
        schema_rows = tuple(
            tuple(row)
            for row in session.execute(
                text(
                    "SELECT type, name, tbl_name, COALESCE(sql, '') "
                    "FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
                    "AND type IN ('table', 'index', 'trigger') "
                    "ORDER BY type, name"
                )
            )
        )
        schema_tables = tuple(
            str(name)
            for name in session.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ).scalars()
        )
        session.execute(
            text(
                "INSERT INTO ironsbot_metadata (key, value) VALUES "
                "('ironsbot_schema_contract_version', '1'), "
                "('ironsbot_schema_tables', :schema_tables), "
                "('ironsbot_schema_fingerprint', :schema_fingerprint), "
                "('render_asset_manifest_revision', 'assets-v1'), "
                "('render_asset_manifest_contract_version', '3'), "
                "('render_asset_manifest_complete_scopes', :scopes), "
                "('render_asset_manifest_repositories', :repositories)"
            ),
            {
                "scopes": json.dumps(scopes),
                "repositories": json.dumps(
                    {
                        "default": {
                            "repository": "Murmansk-Seer/seer-unity-assets",
                            "revision": "a" * 40,
                        }
                    }
                ),
                "schema_tables": json.dumps(schema_tables, separators=(",", ":")),
                "schema_fingerprint": sha256(
                    json.dumps(
                        schema_rows,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest(),
            },
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


def test_peak_season_unloaded_database_is_not_an_absent_season() -> None:
    data = SeerDatabase(DatabaseManager(), merge_connected_mintmarks=True)
    with pytest.raises(DataUnavailableError, match="巅峰赛季数据未加载"):
        data.peak_season_start()


def test_peak_season_read_failure_is_not_an_absent_season(tmp_path: Path) -> None:
    source = tmp_path / "season.sqlite"
    engine, _ = _create_release(source, ())
    databases = DatabaseManager()
    data = SeerDatabase(databases, merge_connected_mintmarks=True)
    try:
        databases.load_from_file("seerapi", str(source))
        assert data.peak_season_start() is None
        with databases.session("seerapi") as session:
            assert session is not None
            session.execute(text("DROP TABLE peak_season"))
            session.commit()
        with pytest.raises(DataUnavailableError, match="巅峰赛季数据读取失败") as error:
            data.peak_season_start()
        assert error.value.__cause__ is not None
    finally:
        databases.close()
        engine.dispose()


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
        "default=Murmansk-Seer/seer-unity-assets@"
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
                "CREATE TABLE peak_cost_pool (id INTEGER PRIMARY KEY, cost INTEGER, "
                "start_time TEXT, end_time TEXT)"
            )
        )
        session.execute(text("ALTER TABLE pet ADD COLUMN peak_cost_pool_id INTEGER"))
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


@pytest.mark.parametrize(
    ("metadata_key", "metadata_value", "error_field"),
    [
        (
            "render_asset_manifest_complete_scopes",
            "not-json",
            "render_asset_manifest_complete_scopes",
        ),
        (
            "render_asset_manifest_repositories",
            "not-json",
            "render asset manifest",
        ),
        (
            "ironsbot_schema_tables",
            "not-json",
            "schema table manifest",
        ),
        (
            "ironsbot_schema_fingerprint",
            "0" * 64,
            "schema table manifest",
        ),
    ],
)
def test_seer_database_rejects_invalid_publication_metadata(
    tmp_path: Path,
    metadata_key: str,
    metadata_value: str,
    error_field: str,
) -> None:
    source = tmp_path / "seerapi.sqlite"
    engine, generated_at = _create_release(source, ("pet_info",))
    databases = DatabaseManager()
    data = SeerDatabase(databases, merge_connected_mintmarks=True)
    databases.load_from_file("seerapi", str(source))
    expected_version = f"{generated_at.replace(tzinfo=None).isoformat()}:assets-v1"
    original_snapshot = data.render_asset_snapshot()
    assert original_snapshot is not None

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ironsbot_metadata SET value=:value WHERE key=:key"),
            {"key": metadata_key, "value": metadata_value},
        )

    with pytest.raises(SeerApiReleaseContractError, match=error_field):
        databases.load_from_file("seerapi", str(source))

    assert data.version() == expected_version
    assert data.render_asset_snapshot() is original_snapshot
    databases.close()
    engine.dispose()


def test_seer_database_rejects_a_declared_table_removed_from_release(
    tmp_path: Path,
) -> None:
    source = tmp_path / "seerapi.sqlite"
    engine, _ = _create_release(source, ())
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE activity"))

    databases = DatabaseManager()
    SeerDatabase(databases, merge_connected_mintmarks=True)
    try:
        with pytest.raises(SeerApiReleaseContractError, match="activity"):
            databases.load_from_file("seerapi", str(source))
        assert databases.get_engine("seerapi") is None
    finally:
        databases.close()
        engine.dispose()


def _update_asset_release(engine: Engine, revision: str, manifest: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ironsbot_metadata SET value=:value WHERE key=:key"),
            [
                {
                    "key": "render_asset_manifest_repositories",
                    "value": json.dumps(
                        {
                            "default": {
                                "repository": "Murmansk-Seer/seer-unity-assets",
                                "revision": revision,
                            }
                        }
                    ),
                },
                {"key": "render_asset_manifest_revision", "value": manifest},
            ],
        )


def test_lineup_entries_remain_bound_after_database_replacement(tmp_path: Path) -> None:
    master_pool_cost = 35
    source = tmp_path / "seerapi.sqlite"
    engine, _ = _create_release(source, ("peak_pool",))
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE skin_image_resolution (skin_id INTEGER PRIMARY KEY, "
            "head_resource_id INTEGER, body_resource_id INTEGER, "
            "head_resolution TEXT, body_resolution TEXT, source_pet_id INTEGER)"
        )
        connection.execute(
            SQLModel.metadata.tables["element_type_combination"].insert(),
            [{"id": 4, "name": "type", "name_en": "type", "primary_id": 4}],
        )
        connection.execute(
            SQLModel.metadata.tables["pet"].insert(),
            [
                {
                    "id": 7,
                    "name": "old",
                    "yielding_exp": 0,
                    "catch_rate": 0,
                    "releaseable": False,
                    "fusion_master": False,
                    "fusion_sub": False,
                    "has_resistance": False,
                    "resource_id": 1007,
                    "type_id": 4,
                    "gender_id": 0,
                    "base_stats_id": 0,
                    "yielding_ev_id": 0,
                }
            ],
        )
        connection.execute(
            text(
                "INSERT INTO peak_cost_pool(id, cost, start_time, end_time) "
                f"VALUES (1, {master_pool_cost}, '2026-08-01T00:00:00+00:00', "
                "'2026-09-01T00:00:00+00:00')"
            )
        )
        connection.execute(text("UPDATE pet SET peak_cost_pool_id=1 WHERE id=7"))
    databases = DatabaseManager()
    data = SeerDatabase(databases, merge_connected_mintmarks=True)
    slots = (
        PlayerLineupSlot(pet_id=7, level=100, use_flag=1, skin_id=0),
        PlayerLineupSlot(pet_id=7, level=100, use_flag=1, skin_id=999),
        PlayerLineupSlot(pet_id=999, level=100, use_flag=1, skin_id=0),
    )
    try:
        databases.load_from_file("seerapi", str(source))
        with data.read_snapshot() as bound:
            resolver = PublishedPlayerLineupEntryResolver(bound)
            original = resolver.resolve(slots)
            assert original[0].name == "old"
            assert (original[0].resource_id, original[0].type_id) == (1007, 4)
            assert original[0].master_pool_cost == master_pool_cost
            assert original[0].complete
            assert not original[1].complete and original[1].resource_id == 0
            assert not original[2].complete and original[2].resource_id == 0
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "UPDATE pet SET name='new', resource_id=2007"
                )
            databases.load_from_file("seerapi", str(source))
            assert resolver.resolve(slots) == original
            with data.read_snapshot() as fresh:
                updated = PublishedPlayerLineupEntryResolver(fresh).resolve(slots)
                assert (updated[0].name, updated[0].resource_id) == ("new", 2007)
        assert original[0].name == "old"
        with pytest.raises(DataUnavailableError, match="snapshot is closed"):
            resolver.resolve(slots)
    finally:
        databases.close()
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("category", "scope", "kind"),
    [("pet_info", "pet_info", "pet_body"), ("player_lineup", "peak_pool", "pet_head")],
)
async def test_render_inputs_stay_bound_across_publication_and_rollback(
    tmp_path: Path,
    category: str,
    scope: str,
    kind: ImageKind,
) -> None:
    source = tmp_path / "seerapi.sqlite"
    engine, _ = _create_release(source, (scope,))
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
            spawn=TaskOwner().create,
        )
        versions = RenderCacheVersion(data.version, ())
        cache = FileRenderCache(tmp_path / "renders", 1024, version_getter=versions)
        sessions = SeerRenderSessions(data, clients, assets, cache, versions)
        try:
            await _check_bound_render_inputs(
                sessions, engine, databases, source, category=category, kind=kind
            )
            before = len(requests)
            with sessions.open() as restored:
                assert restored.cache.entry(category, "1").get() == b"old-render"
                assert await restored.images.fetch(kind, "1", fallback=False) == b"old"
            assert len(requests) == before
            assert any("b" * 40 in url for url in requests)
        finally:
            databases.close()
            engine.dispose()


def test_retained_content_index_is_checked_against_bound_publication(
    tmp_path: Path,
) -> None:
    source = tmp_path / "seerapi.sqlite"
    engine, _ = _create_release(source, ("new_content_standard",))
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE new_content_release (id INTEGER PRIMARY KEY, "
            "current_config_version TEXT, weekly_cycle TEXT, "
            "baseline_established INTEGER)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE new_content_item (category TEXT, entity_id INTEGER, "
            "name TEXT, sort_value INTEGER, payload_json TEXT, change_kind TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE new_content_category_state "
            "(category TEXT, comparison_ready INTEGER, reason TEXT)"
        )
        connection.exec_driver_sql(
            "INSERT INTO new_content_release VALUES (1, '20260912', '2026-09-11', 1)"
        )
        connection.exec_driver_sql(
            "INSERT INTO new_content_item VALUES ('skill', 1, 'old', 1, '{}', 'added')"
        )
    databases = DatabaseManager()
    data = SeerDatabase(databases, merge_connected_mintmarks=True)
    try:
        databases.load_from_file("seerapi", str(source))
        with data.read_snapshot() as bound:
            bound.require_current()
            service = NewContentService(PublishedNewContentRepository(bound))
            menu = service.snapshot()
            with engine.begin() as connection:
                connection.exec_driver_sql("UPDATE new_content_item SET name = 'new'")
            databases.load_from_file("seerapi", str(source))
            with pytest.raises(DataPublicationChangedError):
                bound.require_current()
            service.require_snapshot(menu)
            assert service.snapshot().items[0].name == "old"
            with data.read_snapshot() as fresh:
                fresh.require_current()
                current = NewContentService(PublishedNewContentRepository(fresh))
                with pytest.raises(NewContentSnapshotChangedError):
                    current.require_snapshot(menu)
                assert current.snapshot().items[0].name == "new"
                # Even reloading identical metadata is a different generation.
                databases.load_from_file("seerapi", str(source))
                with pytest.raises(DataPublicationChangedError):
                    fresh.require_current()
            with pytest.raises(DataUnavailableError, match="snapshot is closed"):
                fresh.require_current()
            with engine.begin() as connection:
                connection.exec_driver_sql("UPDATE new_content_item SET name = 'old'")
            databases.load_from_file("seerapi", str(source))
            assert NewContentService(
                PublishedNewContentRepository(data)
            ).snapshot() == menu
            with pytest.raises(DataPublicationChangedError):
                bound.require_current()
    finally:
        databases.close()
        engine.dispose()


async def _check_bound_render_inputs(  # noqa: PLR0913 - publication test inputs
    sessions: SeerRenderSessions,
    engine: Engine,
    databases: DatabaseManager,
    source: Path,
    *,
    category: str,
    kind: ImageKind,
) -> None:
    with sessions.open() as old:
        old_entry = old.cache.entry(category, "1")
        assert old_entry.get() is None
        assert await old.images.fetch(kind, "1", fallback=False) == b"old"
        _update_asset_release(engine, "b" * 40, "assets-v2")
        await asyncio.to_thread(databases.load_from_file, "seerapi", str(source))
        with sessions.open() as fresh:
            fresh_entry = fresh.cache.entry(category, "1")
            assert fresh_entry.get() is None
            assert await fresh.images.fetch(kind, "1", fallback=False) == b"new"
            assert await old.images.fetch(kind, "2", fallback=False) == b"old"
            fresh_entry.put(b"new-render")
            old_entry.put(b"old-render")
            assert fresh_entry.get() == b"new-render"
        assert old_entry.get() == b"old-render"
    _update_asset_release(engine, "a" * 40, "assets-v1")
    await asyncio.to_thread(databases.load_from_file, "seerapi", str(source))
