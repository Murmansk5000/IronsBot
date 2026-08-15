# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from seerapi_models import ApiMetadataORM
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from ironsbot.integrations.db_registry import DatabaseManager
from ironsbot.integrations.seer_data.database import SeerDatabase

if TYPE_CHECKING:
    from pathlib import Path


def test_seer_database_version_updates_only_when_database_is_loaded(
    tmp_path: Path,
) -> None:
    source = tmp_path / "seerapi.sqlite"
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
                "('render_asset_manifest_revision', 'assets-v1'), "
                "('render_asset_manifest_contract_version', '2'), "
                "('render_asset_manifest_complete_scopes', '[\"pet_info\"]'), "
                "('render_asset_manifest_asset_repository', "
                "'Murmansk-Seer/seer-unity-assets'), "
                "('render_asset_manifest_asset_repository_revision', "
                "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')"
            )
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

    databases = DatabaseManager()
    data = SeerDatabase(databases, merge_connected_mintmarks=True)

    assert data.version() == "unknown"

    databases.load_from_file("seerapi", str(source))

    expected_version = f"{generated_at.replace(tzinfo=None).isoformat()}:assets-v1"
    assert data.version() == expected_version
    assert data.render_category_available("pet_info")
    assert not data.render_category_available("new_content")
    assert data.render_asset_snapshot() is not None
    assert data.render_asset_cache_identity() == (
        "Murmansk-Seer/seer-unity-assets@"
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:assets-v1"
    )


def test_seer_database_version_rejects_release_without_asset_manifest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "seerapi.sqlite"
    engine = create_engine(f"sqlite:///{source}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
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
    databases.load_from_file("seerapi", str(source))

    assert data.version() == "unknown"
    assert data.render_asset_snapshot() is None
