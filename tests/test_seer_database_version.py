# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest
from seerapi_models import ApiMetadataORM
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from ironsbot.integrations.db_registry import DatabaseManager
from ironsbot.integrations.seer_data.database import SeerDatabase
from ironsbot.integrations.seer_data.release_contract import SeerApiReleaseContractError

if TYPE_CHECKING:
    from pathlib import Path


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

    databases = DatabaseManager()
    data = SeerDatabase(databases, merge_connected_mintmarks=True)

    assert data.version() == "unknown"

    databases.load_from_file("seerapi", str(source))

    expected_version = f"{generated_at.replace(tzinfo=None).isoformat()}:assets-v1"
    assert data.version() == expected_version
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
