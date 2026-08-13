# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from seerapi_models import ApiMetadataORM
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

    assert data.version() == generated_at.replace(tzinfo=None).isoformat()
